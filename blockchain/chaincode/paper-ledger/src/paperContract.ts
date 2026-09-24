/**
 * paperContract.ts — Phase 5A chaincode (LLD Sections 9-10, scoped down
 * per the Phase 5 readiness inspection to exactly the 4 transactions the
 * FastAPI backend actually needs — see PROJECT_STATE.md's Phase 5
 * readiness section for why CC-01..CC-09's other functions were not
 * reproduced here 1:1).
 *
 * Binding constraint (SEC-001/SEC-010): this chaincode NEVER accepts or
 * stores the question-paper PDF, AES keys, wrapped DEKs, passwords,
 * OTPs, or JWTs. Only metadata, hashes, and short audit fields cross
 * this boundary — enforced by the parameter lists below, not by any
 * runtime filtering (there is nothing to filter: the file/key material
 * never leaves the FastAPI backend's process memory in the first
 * place).
 */

import { Context, Contract, Info, Returns, Transaction } from "fabric-contract-api";

interface PaperRecord {
  docType: "paper";
  paperId: string;
  sha256Hash: string;
  registeredAt: string;
  adminId: string;
  subject: string;
  encryptionAlgorithm: string;
}

interface AuditEventRecord {
  docType: "auditEvent";
  eventId: string;
  eventType: string;
  actorId: string;
  paperId: string;
  outcome: string;
  timestamp: string;
}

function paperKey(paperId: string): string {
  return `PAPER_${paperId}`;
}

function auditEventKey(eventId: string): string {
  // Deterministic key derived from eventId (per Phase 5A instructions):
  // any attempt to record the same eventId twice hits the same
  // world-state key, so a duplicate is detected by existence-check
  // below rather than silently creating two records.
  return `AUDIT_${eventId}`;
}

function requireNonEmpty(value: string | undefined | null, fieldName: string): asserts value is string {
  if (value === undefined || value === null || value.trim().length === 0) {
    throw new Error(`VALIDATION_ERROR: '${fieldName}' is required and must not be empty.`);
  }
}

@Info({ title: "PaperLedgerContract", description: "Phase 5A minimal question-paper ledger chaincode" })
export class PaperLedgerContract extends Contract {
  /**
   * RegisterPaper — records a newly registered paper's immutable
   * metadata and SHA-256 hash on the ledger. Rejects a paper_id that
   * already exists (duplicate registration is a hard error, not an
   * idempotent no-op, since a duplicate here would mean two different
   * PDFs are claiming the same identity).
   */
  @Transaction()
  @Returns("string")
  public async RegisterPaper(
    ctx: Context,
    paperId: string,
    sha256Hash: string,
    registeredAt: string,
    adminId: string,
    subject: string,
    encryptionAlgorithm: string
  ): Promise<string> {
    requireNonEmpty(paperId, "paper_id");
    requireNonEmpty(sha256Hash, "sha256_hash");
    requireNonEmpty(registeredAt, "registered_at");
    requireNonEmpty(adminId, "admin_id");
    requireNonEmpty(subject, "subject");
    requireNonEmpty(encryptionAlgorithm, "encryption_algorithm");

    if (!/^[0-9a-fA-F]{64}$/.test(sha256Hash)) {
      throw new Error("VALIDATION_ERROR: 'sha256_hash' must be a 64-character hexadecimal SHA-256 digest.");
    }

    const key = paperKey(paperId);
    const existing = await ctx.stub.getState(key);
    if (existing && existing.length > 0) {
      throw new Error(`DUPLICATE_PAPER: paper_id '${paperId}' is already registered on the ledger.`);
    }

    const record: PaperRecord = {
      docType: "paper",
      paperId,
      sha256Hash,
      registeredAt,
      adminId,
      subject,
      encryptionAlgorithm,
    };

    await ctx.stub.putState(key, Buffer.from(JSON.stringify(record)));
    return ctx.stub.getTxID();
  }

  /**
   * GetPaper — read-only lookup of a previously registered paper's
   * full metadata record. Returns a clear not-found error rather than
   * an empty/null payload, so callers cannot mistake "no record" for
   * "record with empty fields."
   */
  @Transaction(false)
  @Returns("string")
  public async GetPaper(ctx: Context, paperId: string): Promise<string> {
    requireNonEmpty(paperId, "paper_id");

    const bytes = await ctx.stub.getState(paperKey(paperId));
    if (!bytes || bytes.length === 0) {
      throw new Error(`PAPER_NOT_FOUND: no paper is registered with paper_id '${paperId}'.`);
    }
    return Buffer.from(bytes).toString("utf8");
  }

  /**
   * VerifyPaperHash — compares a candidate SHA-256 hash against the
   * hash recorded at registration time. Does NOT modify the stored
   * record (read-only). Comparison logic lives on-chain so a
   * verification result is independently reproducible by any client
   * with ledger read access, not just by the party holding the
   * original file.
   */
  @Transaction(false)
  @Returns("string")
  public async VerifyPaperHash(ctx: Context, paperId: string, candidateHash: string): Promise<string> {
    requireNonEmpty(paperId, "paper_id");
    requireNonEmpty(candidateHash, "candidate_hash");

    const bytes = await ctx.stub.getState(paperKey(paperId));
    if (!bytes || bytes.length === 0) {
      throw new Error(`PAPER_NOT_FOUND: no paper is registered with paper_id '${paperId}'.`);
    }
    const record: PaperRecord = JSON.parse(Buffer.from(bytes).toString("utf8"));

    const match = record.sha256Hash.toLowerCase() === candidateHash.toLowerCase();
    return JSON.stringify({ paper_id: paperId, match });
  }

  /**
   * RecordAuditEvent — appends an immutable audit record. Rejects a
   * duplicate event_id outright (see auditEventKey's docstring) rather
   * than silently overwriting, since audit records must never be
   * editable after creation (LLD Section 4.9's "must not be editable
   * after creation" requirement, now enforced ON-CHAIN, not just by
   * application-layer discipline in audit_service.py).
   *
   * Deliberately does NOT accept or store: passwords, OTPs, JWTs, PDF
   * content, or encryption keys — there is no parameter through which
   * any of those could even be passed.
   */
  @Transaction()
  @Returns("string")
  public async RecordAuditEvent(
    ctx: Context,
    eventId: string,
    eventType: string,
    actorId: string,
    paperId: string,
    outcome: string,
    timestamp: string
  ): Promise<string> {
    requireNonEmpty(eventId, "event_id");
    requireNonEmpty(eventType, "event_type");
    requireNonEmpty(outcome, "outcome");
    requireNonEmpty(timestamp, "timestamp");
    // actorId / paperId MAY legitimately be empty (e.g. a system-level
    // event with no human actor, or an event not tied to a specific
    // paper) — mirrors audit_event.py's nullable actor_id/paper_id
    // columns in PostgreSQL. Not required, unlike the fields above.

    const key = auditEventKey(eventId);
    const existing = await ctx.stub.getState(key);
    if (existing && existing.length > 0) {
      throw new Error(`DUPLICATE_EVENT: event_id '${eventId}' has already been recorded on the ledger.`);
    }

    const record: AuditEventRecord = {
      docType: "auditEvent",
      eventId,
      eventType,
      actorId: actorId ?? "",
      paperId: paperId ?? "",
      outcome,
      timestamp,
    };

    await ctx.stub.putState(key, Buffer.from(JSON.stringify(record)));
    return ctx.stub.getTxID();
  }
}
