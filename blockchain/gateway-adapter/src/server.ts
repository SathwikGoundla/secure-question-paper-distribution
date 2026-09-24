/**
 * server.ts — internal HTTP API for the Gateway Adapter.
 *
 * Binds to 127.0.0.1 only (see main() at the bottom) — this is an
 * internal service; FastAPI is the only public-facing application in
 * this architecture (Internet -> FastAPI -> localhost adapter ->
 * Fabric). No authentication is added here yet, per the Phase 5B
 * brief — that boundary is enforced by the bind address, not by this
 * phase's scope.
 */

import express, { NextFunction, Request, Response } from "express";
import { EndorseError, GatewayError } from "@hyperledger/fabric-gateway";
import { closeGateway, getContract, isGatewayConnected } from "./fabricGateway";
import {
  AuditEventRequest,
  AuditEventResponse,
  ErrorResponse,
  HealthResponse,
  RegisterPaperRequest,
  RegisterPaperResponse,
  VerifyHashRequest,
  VerifyHashResponse,
} from "./types";

const app = express();
app.use(express.json());

const decoder = new TextDecoder("utf-8");

// --- Error classification -------------------------------------------------
//
// Chaincode errors (paperContract.ts) always start with a short
// UPPER_SNAKE_CASE prefix ("PAPER_NOT_FOUND:", "DUPLICATE_PAPER:",
// "DUPLICATE_EVENT:", "VALIDATION_ERROR:") — this maps those prefixes
// to HTTP status codes, mirroring the mapping style already used in
// the FastAPI backend's exception hierarchy (app/exceptions/base.py),
// so the two layers stay consistent in spirit even though they are
// separate codebases.
const PREFIX_STATUS_MAP: Array<{ prefix: string; status: number; type: string }> = [
  { prefix: "PAPER_NOT_FOUND", status: 404, type: "NOT_FOUND" },
  { prefix: "DUPLICATE_PAPER", status: 409, type: "DUPLICATE" },
  { prefix: "DUPLICATE_EVENT", status: 409, type: "DUPLICATE" },
  { prefix: "VALIDATION_ERROR", status: 400, type: "VALIDATION_ERROR" },
];

function extractChaincodeMessage(err: unknown): string | undefined {
  if (err instanceof GatewayError && err.details.length > 0) {
    return err.details[0].message;
  }
  return undefined;
}

/**
 * Maps any error thrown by a Fabric call into a clean (status, body)
 * pair. Never includes private key/certificate contents or raw stack
 * traces in the response — those stay server-side in the console log
 * only (see the error-handling middleware below).
 */
function classifyError(err: unknown): { status: number; body: ErrorResponse } {
  const chaincodeMessage = extractChaincodeMessage(err);
  if (chaincodeMessage) {
    const match = PREFIX_STATUS_MAP.find((m) => chaincodeMessage.includes(m.prefix));
    if (match) {
      return { status: match.status, body: { error: { message: chaincodeMessage, type: match.type } } };
    }
    // A GatewayError with details but no recognised prefix is still a
    // genuine chaincode-level rejection — surface it as a 400 rather
    // than masking it as a generic 500 "server error".
    return { status: 400, body: { error: { message: chaincodeMessage, type: "CHAINCODE_ERROR" } } };
  }

  if (err instanceof EndorseError) {
    return { status: 502, body: { error: { message: "Endorsement failed.", type: "ENDORSE_FAILED" } } };
  }
  if (err instanceof GatewayError) {
    return { status: 502, body: { error: { message: "Fabric Gateway error.", type: "GATEWAY_ERROR" } } };
  }

  const message = err instanceof Error ? err.message : String(err);
  if (/Missing required environment variable|Failed to read/.test(message)) {
    return { status: 503, body: { error: { message: "Fabric adapter is not correctly configured.", type: "CONFIGURATION_ERROR" } } };
  }
  if (/deadline|DEADLINE_EXCEEDED|UNAVAILABLE/i.test(message)) {
    return { status: 503, body: { error: { message: "Fabric network is unavailable or timed out.", type: "FABRIC_UNAVAILABLE" } } };
  }

  return { status: 500, body: { error: { message: "An internal adapter error occurred.", type: "INTERNAL_ERROR" } } };
}

function asyncHandler(fn: (req: Request, res: Response) => Promise<void>) {
  return (req: Request, res: Response, next: NextFunction): void => {
    fn(req, res).catch(next);
  };
}

// --- Routes -----------------------------------------------------------------

app.get("/health", (_req: Request, res: Response<HealthResponse>) => {
  // Deliberately cheap — reports whether a Gateway connection has been
  // established (lazy-connect-on-first-use), NOT a live round-trip
  // Fabric call, per the Phase 5B brief ("do not make the health
  // endpoint unnecessarily expensive").
  res.json({ status: "ok", service: "fabric-gateway-adapter", fabric_connected: isGatewayConnected() });
});

app.post(
  "/fabric/register-paper",
  asyncHandler(async (req: Request<unknown, unknown, RegisterPaperRequest>, res: Response) => {
    const { paper_id, sha256_hash, registered_at, admin_id, subject, encryption_algorithm } = req.body;
    for (const [key, value] of Object.entries({ paper_id, sha256_hash, registered_at, admin_id, subject, encryption_algorithm })) {
      if (!value || typeof value !== "string") {
        res.status(400).json({ error: { message: `Missing or invalid field: ${key}`, type: "VALIDATION_ERROR" } });
        return;
      }
    }

    const contract = getContract();
    const commit = await contract.submitAsync("RegisterPaper", {
      arguments: [paper_id, sha256_hash, registered_at, admin_id, subject, encryption_algorithm],
    });
    const status = await commit.getStatus();
    if (!status.successful) {
      res.status(409).json({
        error: {
          message: `Transaction committed with unsuccessful status code ${status.code}.`,
          type: "COMMIT_FAILED",
        },
      });
      return;
    }

    const response: RegisterPaperResponse = {
      success: true,
      transaction_id: status.transactionId,
      paper_id,
    };
    res.status(201).json(response);
  })
);

app.get(
  "/fabric/paper/:paper_id",
  asyncHandler(async (req: Request, res: Response) => {
    const paperId = req.params.paper_id;
    const contract = getContract();
    const resultBytes = await contract.evaluateTransaction("GetPaper", paperId);
    res.status(200).json(JSON.parse(decoder.decode(resultBytes)));
  })
);

app.post(
  "/fabric/verify-hash",
  asyncHandler(async (req: Request<unknown, unknown, VerifyHashRequest>, res: Response) => {
    const { paper_id, candidate_hash } = req.body;
    if (!paper_id || !candidate_hash) {
      res.status(400).json({ error: { message: "paper_id and candidate_hash are required.", type: "VALIDATION_ERROR" } });
      return;
    }

    const contract = getContract();
    const resultBytes = await contract.evaluateTransaction("VerifyPaperHash", paper_id, candidate_hash);
    const result: VerifyHashResponse = JSON.parse(decoder.decode(resultBytes));
    res.status(200).json(result);
  })
);

app.post(
  "/fabric/audit-event",
  asyncHandler(async (req: Request<unknown, unknown, AuditEventRequest>, res: Response) => {
    const { event_id, event_type, actor_id, paper_id, outcome, timestamp } = req.body;
    for (const [key, value] of Object.entries({ event_id, event_type, outcome, timestamp })) {
      if (!value || typeof value !== "string") {
        res.status(400).json({ error: { message: `Missing or invalid field: ${key}`, type: "VALIDATION_ERROR" } });
        return;
      }
    }

    const contract = getContract();
    const commit = await contract.submitAsync("RecordAuditEvent", {
      // actor_id / paper_id may legitimately be empty strings (see
      // paperContract.ts) — never undefined, so coerce here.
      arguments: [event_id, event_type, actor_id ?? "", paper_id ?? "", outcome, timestamp],
    });
    const status = await commit.getStatus();
    if (!status.successful) {
      res.status(409).json({
        error: { message: `Transaction committed with unsuccessful status code ${status.code}.`, type: "COMMIT_FAILED" },
      });
      return;
    }

    const response: AuditEventResponse = { success: true, transaction_id: status.transactionId, event_id };
    res.status(201).json(response);
  })
);

// --- Error-handling middleware (must be registered LAST) -------------------
// eslint-disable-next-line @typescript-eslint/no-unused-vars
app.use((err: unknown, _req: Request, res: Response<ErrorResponse>, _next: NextFunction) => {
  // Full detail (including stack trace) goes to the server-side console
  // only — never into the HTTP response. No private key / certificate
  // material can appear here since classifyError() only ever surfaces
  // chaincode messages or short, fixed strings.
  // eslint-disable-next-line no-console
  console.error("Request failed:", err);
  const { status, body } = classifyError(err);
  res.status(status).json(body);
});

export function createApp() {
  return app;
}

function main(): void {
  const port = Number(process.env.ADAPTER_PORT ?? 8081);
  const host = "127.0.0.1"; // internal-only service — never bind 0.0.0.0 (see module docstring)
  const server = app.listen(port, host, () => {
    // eslint-disable-next-line no-console
    console.log(`fabric-gateway-adapter listening on http://${host}:${port}`);
  });

  const shutdown = (): void => {
    // eslint-disable-next-line no-console
    console.log("Shutting down fabric-gateway-adapter...");
    closeGateway();
    server.close(() => process.exit(0));
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

if (require.main === module) {
  main();
}
