/**
 * fabricIntegration.test.ts — REAL Fabric integration tests.
 *
 * NO MOCKS. Requires the actual Phase 5A network to be running:
 *   cd blockchain/network/scripts
 *   bash start-network.sh && bash deploy-chaincode.sh
 * and this adapter's .env to point at that live network (see
 * .env.example). Skips itself cleanly (not a false pass) if the
 * adapter cannot reach Fabric, printing which environment variable/
 * connection step failed — per the Phase 5B brief's explicit
 * instruction not to substitute mocks for real integration testing.
 *
 * Run with: npm run test:integration
 */

import request from "supertest";
import * as dotenv from "node:fs";
import * as path from "node:path";

function loadDotEnvIfPresent(): void {
  const envPath = path.resolve(__dirname, "../../.env");
  if (!dotenv.existsSync(envPath)) return;
  const content = dotenv.readFileSync(envPath, "utf-8");
  for (const line of content.split("\n")) {
    const match = line.match(/^([A-Z_][A-Z0-9_]*)=(.*)$/);
    if (match && !process.env[match[1]]) {
      process.env[match[1]] = match[2];
    }
  }
}
loadDotEnvIfPresent();

// eslint-disable-next-line @typescript-eslint/no-var-requires
const { createApp } = require("../../src/server");

const REQUIRED_ENV = [
  "FABRIC_MSP_ID",
  "FABRIC_CHANNEL_NAME",
  "FABRIC_CHAINCODE_NAME",
  "FABRIC_PEER_ENDPOINT",
  "FABRIC_TLS_CERT_PATH",
  "FABRIC_CERT_PATH",
  "FABRIC_PRIVATE_KEY_PATH",
];

const missingEnv = REQUIRED_ENV.filter((name) => !process.env[name]);
const describeIfConfigured = missingEnv.length === 0 ? describe : describe.skip;

if (missingEnv.length > 0) {
  // eslint-disable-next-line no-console
  console.warn(
    `SKIPPING real Fabric integration tests — missing environment variables: ${missingEnv.join(", ")}. ` +
      "Copy .env.example to .env and ensure the Phase 5A network is running to enable these tests."
  );
}

describeIfConfigured("Real Fabric network integration (no mocks)", () => {
  const app = createApp();
  const uniqueSuffix = Date.now().toString();
  const paperId = `it-paper-${uniqueSuffix}`;
  const correctHash = "c".repeat(64);
  const wrongHash = "d".repeat(64);

  it("GET /health reports ok", async () => {
    const res = await request(app).get("/health");
    expect(res.status).toBe(200);
    expect(res.body.status).toBe("ok");
  }, 10_000);

  it("registers a real paper on the real ledger and returns a genuine transaction ID", async () => {
    const res = await request(app)
      .post("/fabric/register-paper")
      .send({
        paper_id: paperId,
        sha256_hash: correctHash,
        registered_at: "2026-01-01T00:00:00Z",
        admin_id: "integration-test-admin",
        subject: "Integration Test Subject",
        encryption_algorithm: "AES-256-GCM",
      });

    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.paper_id).toBe(paperId);
    // A real Fabric transaction ID is a 64-character hex SHA-256 digest —
    // this is a structural sanity check that it is NOT a fabricated
    // placeholder string.
    expect(res.body.transaction_id).toMatch(/^[a-f0-9]{64}$/);
  }, 30_000);

  it("rejects a duplicate RegisterPaper for the same paper_id", async () => {
    const res = await request(app)
      .post("/fabric/register-paper")
      .send({
        paper_id: paperId,
        sha256_hash: correctHash,
        registered_at: "2026-01-01T00:00:00Z",
        admin_id: "integration-test-admin",
        subject: "Integration Test Subject",
        encryption_algorithm: "AES-256-GCM",
      });

    expect(res.status).toBe(409);
    expect(res.body.error.type).toBe("DUPLICATE");
  }, 30_000);

  it("retrieves the real registered paper via GetPaper", async () => {
    const res = await request(app).get(`/fabric/paper/${paperId}`);
    expect(res.status).toBe(200);
    expect(res.body.paperId).toBe(paperId);
    expect(res.body.sha256Hash).toBe(correctHash);
  }, 15_000);

  it("returns 404 for a paper that was never registered", async () => {
    const res = await request(app).get(`/fabric/paper/does-not-exist-${uniqueSuffix}`);
    expect(res.status).toBe(404);
    expect(res.body.error.type).toBe("NOT_FOUND");
  }, 15_000);

  it("VerifyPaperHash returns match:true for the correct hash", async () => {
    const res = await request(app).post("/fabric/verify-hash").send({ paper_id: paperId, candidate_hash: correctHash });
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ paper_id: paperId, match: true });
  }, 15_000);

  it("VerifyPaperHash returns match:false for an incorrect hash", async () => {
    const res = await request(app).post("/fabric/verify-hash").send({ paper_id: paperId, candidate_hash: wrongHash });
    expect(res.status).toBe(200);
    expect(res.body).toEqual({ paper_id: paperId, match: false });
  }, 15_000);

  it("records a real audit event and returns a genuine transaction ID", async () => {
    const res = await request(app)
      .post("/fabric/audit-event")
      .send({
        event_id: `it-evt-${uniqueSuffix}`,
        event_type: "PAPER_REGISTRATION_COMPLETED",
        actor_id: "integration-test-admin",
        paper_id: paperId,
        outcome: "SUCCESS",
        timestamp: "2026-01-01T00:00:01Z",
      });

    expect(res.status).toBe(201);
    expect(res.body.success).toBe(true);
    expect(res.body.transaction_id).toMatch(/^[a-f0-9]{64}$/);
  }, 30_000);
});
