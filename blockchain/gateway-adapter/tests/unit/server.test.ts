/**
 * server.test.ts — HTTP-layer unit tests.
 *
 * These tests MOCK the Fabric contract entirely (via jest.mock of
 * ./fabricGateway) — they verify request validation, response
 * shaping, and error-status mapping WITHOUT a real Fabric network.
 *
 * This is deliberately kept separate from tests/integration/, which
 * requires a REAL running Phase 5A network and makes NO use of mocks —
 * per the Phase 5B brief's explicit instruction not to substitute
 * mocks for real integration testing and then claim Fabric works.
 */

import request from "supertest";

// The real @hyperledger/fabric-gateway package transitively pulls in
// an ESM-only dependency (@noble/curves) that ts-jest's default
// CommonJS transform cannot parse. Since this file is a pure HTTP-
// layer unit test (no real Fabric connection involved at all), the
// whole package is mocked here with minimal, behaviourally-correct
// stand-ins for the two error classes server.ts actually uses
// (`instanceof` checks must still work) — this mock applies to
// server.ts's import of the same module specifier too.
class FakeGatewayError extends Error {
  code: number;
  details: Array<{ address: string; mspId: string; message: string }>;
  constructor(props: { code: number; details: Array<{ address: string; mspId: string; message: string }>; cause?: unknown; message?: string }) {
    super(props.message ?? props.details[0]?.message ?? "gateway error");
    this.code = props.code;
    this.details = props.details;
  }
}
class FakeEndorseError extends FakeGatewayError {}

jest.mock("@hyperledger/fabric-gateway", () => ({
  GatewayError: FakeGatewayError,
  EndorseError: FakeEndorseError,
}));

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { GatewayError } = require("@hyperledger/fabric-gateway");

const mockEvaluateTransaction = jest.fn();
const mockSubmitAsync = jest.fn();

jest.mock("../../src/fabricGateway", () => ({
  getContract: () => ({
    evaluateTransaction: mockEvaluateTransaction,
    submitAsync: mockSubmitAsync,
  }),
  isGatewayConnected: () => true,
  closeGateway: jest.fn(),
}));

// Imported AFTER the mock is registered.
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { createApp } = require("../../src/server");

const encoder = new TextEncoder();

describe("GET /health", () => {
  it("reports ok without touching Fabric", async () => {
    const res = await request(createApp()).get("/health");
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ status: "ok", service: "fabric-gateway-adapter", fabric_connected: true });
    expect(mockEvaluateTransaction).not.toHaveBeenCalled();
    expect(mockSubmitAsync).not.toHaveBeenCalled();
  });
});

describe("POST /fabric/register-paper", () => {
  beforeEach(() => jest.clearAllMocks());

  it("returns 201 with a transaction_id on success", async () => {
    mockSubmitAsync.mockResolvedValue({
      getStatus: async () => ({ successful: true, transactionId: "tx-123", code: 0 }),
    });

    const res = await request(createApp()).post("/fabric/register-paper").send({
      paper_id: "paper-1",
      sha256_hash: "a".repeat(64),
      registered_at: "2026-01-01T00:00:00Z",
      admin_id: "admin-1",
      subject: "Demo",
      encryption_algorithm: "AES-256-GCM",
    });

    expect(res.status).toBe(201);
    expect(res.body).toEqual({ success: true, transaction_id: "tx-123", paper_id: "paper-1" });
    expect(mockSubmitAsync).toHaveBeenCalledWith("RegisterPaper", {
      arguments: ["paper-1", "a".repeat(64), "2026-01-01T00:00:00Z", "admin-1", "Demo", "AES-256-GCM"],
    });
  });

  it("returns 400 when a required field is missing", async () => {
    const res = await request(createApp()).post("/fabric/register-paper").send({ paper_id: "paper-1" });
    expect(res.status).toBe(400);
    expect(res.body.error.type).toBe("VALIDATION_ERROR");
    expect(mockSubmitAsync).not.toHaveBeenCalled();
  });

  it("maps a DUPLICATE_PAPER chaincode error to 409", async () => {
    const err = new GatewayError({
      code: 1,
      cause: new Error("cause") as any,
      details: [{ address: "peer0:7051", mspId: "Org1MSP", message: "DUPLICATE_PAPER: paper_id 'paper-1' is already registered on the ledger." }],
    });
    mockSubmitAsync.mockRejectedValue(err);

    const res = await request(createApp()).post("/fabric/register-paper").send({
      paper_id: "paper-1",
      sha256_hash: "a".repeat(64),
      registered_at: "2026-01-01T00:00:00Z",
      admin_id: "admin-1",
      subject: "Demo",
      encryption_algorithm: "AES-256-GCM",
    });

    expect(res.status).toBe(409);
    expect(res.body.error.type).toBe("DUPLICATE");
    expect(res.body.error.message).toContain("DUPLICATE_PAPER");
  });

  it("never leaks a stack trace or key material into the response", async () => {
    mockSubmitAsync.mockRejectedValue(new Error("ENOENT: no such file or directory, open '/some/priv_sk'"));

    const res = await request(createApp()).post("/fabric/register-paper").send({
      paper_id: "paper-1",
      sha256_hash: "a".repeat(64),
      registered_at: "2026-01-01T00:00:00Z",
      admin_id: "admin-1",
      subject: "Demo",
      encryption_algorithm: "AES-256-GCM",
    });

    expect(res.status).toBe(500);
    expect(JSON.stringify(res.body)).not.toMatch(/priv_sk|ENOENT|at Object\./);
  });
});

describe("GET /fabric/paper/:paper_id", () => {
  beforeEach(() => jest.clearAllMocks());

  it("returns the ledger record on success", async () => {
    const record = {
      docType: "paper",
      paperId: "paper-1",
      sha256Hash: "a".repeat(64),
      registeredAt: "2026-01-01T00:00:00Z",
      adminId: "admin-1",
      subject: "Demo",
      encryptionAlgorithm: "AES-256-GCM",
    };
    mockEvaluateTransaction.mockResolvedValue(encoder.encode(JSON.stringify(record)));

    const res = await request(createApp()).get("/fabric/paper/paper-1");
    expect(res.status).toBe(200);
    expect(res.body).toEqual(record);
  });

  it("maps a PAPER_NOT_FOUND chaincode error to 404", async () => {
    const err = new GatewayError({
      code: 1,
      cause: new Error("cause") as any,
      details: [{ address: "peer0:7051", mspId: "Org1MSP", message: "PAPER_NOT_FOUND: no paper is registered with paper_id 'nope'." }],
    });
    mockEvaluateTransaction.mockRejectedValue(err);

    const res = await request(createApp()).get("/fabric/paper/nope");
    expect(res.status).toBe(404);
    expect(res.body.error.type).toBe("NOT_FOUND");
  });
});

describe("POST /fabric/verify-hash", () => {
  beforeEach(() => jest.clearAllMocks());

  it("returns match:true", async () => {
    mockEvaluateTransaction.mockResolvedValue(encoder.encode(JSON.stringify({ paper_id: "paper-1", match: true })));
    const res = await request(createApp()).post("/fabric/verify-hash").send({ paper_id: "paper-1", candidate_hash: "a".repeat(64) });
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ paper_id: "paper-1", match: true });
  });

  it("returns match:false", async () => {
    mockEvaluateTransaction.mockResolvedValue(encoder.encode(JSON.stringify({ paper_id: "paper-1", match: false })));
    const res = await request(createApp()).post("/fabric/verify-hash").send({ paper_id: "paper-1", candidate_hash: "b".repeat(64) });
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ paper_id: "paper-1", match: false });
  });

  it("returns 400 when candidate_hash is missing", async () => {
    const res = await request(createApp()).post("/fabric/verify-hash").send({ paper_id: "paper-1" });
    expect(res.status).toBe(400);
  });
});

describe("POST /fabric/audit-event", () => {
  beforeEach(() => jest.clearAllMocks());

  it("returns 201 with a transaction_id on success", async () => {
    mockSubmitAsync.mockResolvedValue({
      getStatus: async () => ({ successful: true, transactionId: "tx-456", code: 0 }),
    });

    const res = await request(createApp()).post("/fabric/audit-event").send({
      event_id: "evt-1",
      event_type: "PAPER_REGISTRATION_COMPLETED",
      actor_id: "admin-1",
      paper_id: "paper-1",
      outcome: "SUCCESS",
      timestamp: "2026-01-01T00:00:01Z",
    });

    expect(res.status).toBe(201);
    expect(res.body).toEqual({ success: true, transaction_id: "tx-456", event_id: "evt-1" });
  });

  it("maps a DUPLICATE_EVENT chaincode error to 409", async () => {
    const err = new GatewayError({
      code: 1,
      cause: new Error("cause") as any,
      details: [{ address: "peer0:7051", mspId: "Org1MSP", message: "DUPLICATE_EVENT: event_id 'evt-1' has already been recorded on the ledger." }],
    });
    mockSubmitAsync.mockRejectedValue(err);

    const res = await request(createApp()).post("/fabric/audit-event").send({
      event_id: "evt-1",
      event_type: "PAPER_REGISTRATION_COMPLETED",
      actor_id: "admin-1",
      paper_id: "paper-1",
      outcome: "SUCCESS",
      timestamp: "2026-01-01T00:00:01Z",
    });

    expect(res.status).toBe(409);
  });
});

describe("Fabric connection failure", () => {
  beforeEach(() => jest.clearAllMocks());

  it("maps a timeout/unavailable error to 503", async () => {
    mockEvaluateTransaction.mockRejectedValue(new Error("14 UNAVAILABLE: No connection established"));
    const res = await request(createApp()).get("/fabric/paper/paper-1");
    expect(res.status).toBe(503);
    expect(res.body.error.type).toBe("FABRIC_UNAVAILABLE");
  });
});
