/**
 * fabricGateway.ts — connection management for the official
 * @hyperledger/fabric-gateway client (NOT fabric-sdk-py, NOT any CLI
 * subprocess wrapper — a real gRPC connection to the peer's embedded
 * Gateway service).
 *
 * Identity: this phase reuses the same Org1 Admin identity that Phase
 * 5A's network/scripts/*.sh already used for every lifecycle/invoke
 * operation — see PROJECT_STATE.md's Phase 5A section, which
 * confirmed there is no separate, more restricted "application"
 * identity in this project yet. Using Admin here is consistent with
 * that, but is flagged as a production-hardening item for later (a
 * dedicated, narrowly-scoped identity would be preferable once this
 * moves beyond a B.Tech prototype) — not silently treated as
 * permanently fine.
 *
 * Never logs or returns private key / certificate CONTENTS — only
 * file paths (which are not secrets themselves) appear in logs.
 */

import * as crypto from "node:crypto";
import * as fs from "node:fs";
import * as grpc from "@grpc/grpc-js";
import { connect, Contract, Gateway, Identity, Signer, signers } from "@hyperledger/fabric-gateway";

export interface FabricConfig {
  mspId: string;
  channelName: string;
  chaincodeName: string;
  peerEndpoint: string;
  peerHostAlias?: string;
  tlsCertPath: string; // peer TLS root CA (verifies the peer's server certificate)
  certPath: string; // this adapter's own identity certificate (signcert)
  privateKeyPath: string; // this adapter's own identity private key
}

// Timeouts (documented per Phase 5B requirements — see README.md "Timeouts" section):
const EVALUATE_TIMEOUT_MS = 5_000; // read-only queries (GetPaper, VerifyPaperHash) — should be fast
const ENDORSE_TIMEOUT_MS = 15_000; // endorsement round-trip for submitted transactions
const SUBMIT_TIMEOUT_MS = 15_000; // broadcasting the endorsed transaction to the orderer
const COMMIT_STATUS_TIMEOUT_MS = 30_000; // waiting for the transaction to be committed to a block

export function loadFabricConfigFromEnv(): FabricConfig {
  const required = (name: string): string => {
    const value = process.env[name];
    if (!value) {
      throw new Error(`Missing required environment variable: ${name}`);
    }
    return value;
  };

  return {
    mspId: required("FABRIC_MSP_ID"),
    channelName: required("FABRIC_CHANNEL_NAME"),
    chaincodeName: required("FABRIC_CHAINCODE_NAME"),
    peerEndpoint: required("FABRIC_PEER_ENDPOINT"),
    peerHostAlias: process.env.FABRIC_PEER_HOST_ALIAS || undefined,
    tlsCertPath: required("FABRIC_TLS_CERT_PATH"),
    certPath: required("FABRIC_CERT_PATH"),
    privateKeyPath: required("FABRIC_PRIVATE_KEY_PATH"),
  };
}

function readFileOrThrow(path: string, description: string): Buffer {
  try {
    return fs.readFileSync(path);
  } catch (err) {
    // Deliberately do NOT include the underlying fs error's full message
    // in some environments that could echo sensitive path details beyond
    // what's useful — the path itself is not secret, so it's fine to
    // name it, but we keep the wrapping message short and specific.
    throw new Error(`Failed to read ${description} at '${path}': file not found or unreadable.`);
  }
}

function buildIdentity(config: FabricConfig): Identity {
  const certPem = readFileOrThrow(config.certPath, "identity certificate");
  return { mspId: config.mspId, credentials: certPem };
}

function buildSigner(config: FabricConfig): Signer {
  const keyPem = readFileOrThrow(config.privateKeyPath, "identity private key");
  const privateKey = crypto.createPrivateKey(keyPem);
  return signers.newPrivateKeySigner(privateKey);
}

function buildGrpcClient(config: FabricConfig): grpc.Client {
  const tlsRootCert = readFileOrThrow(config.tlsCertPath, "peer TLS root certificate");
  const credentials = grpc.credentials.createSsl(tlsRootCert);
  const options: grpc.ClientOptions = {};
  if (config.peerHostAlias) {
    // Only needed if connecting via an address that doesn't match the
    // hostname the peer's TLS certificate was actually issued for
    // (e.g. port-forwarding under a different name). Phase 5A's
    // network connects using the SAME hostname the cert was issued
    // for (peer0.org1.example.com), so this is unset by default.
    options["grpc.ssl_target_name_override"] = config.peerHostAlias;
    options["grpc.default_authority"] = config.peerHostAlias;
  }
  return new grpc.Client(config.peerEndpoint, credentials, options);
}

let cachedGrpcClient: grpc.Client | undefined;
let cachedGateway: Gateway | undefined;
let cachedConfig: FabricConfig | undefined;

/**
 * Lazily connects on first use, then reuses the same Gateway (and
 * underlying gRPC client) for every subsequent call — this is the
 * pattern the official fabric-gateway docs recommend ("This should be
 * shared by all gateway instances connecting to the same Fabric
 * Gateway"), rather than reconnecting per HTTP request.
 */
export function getGateway(config: FabricConfig = cachedConfig ?? loadFabricConfigFromEnv()): Gateway {
  if (cachedGateway) {
    return cachedGateway;
  }
  cachedConfig = config;
  cachedGrpcClient = buildGrpcClient(config);
  cachedGateway = connect({
    client: cachedGrpcClient,
    identity: buildIdentity(config),
    signer: buildSigner(config),
    evaluateOptions: () => ({ deadline: Date.now() + EVALUATE_TIMEOUT_MS }),
    endorseOptions: () => ({ deadline: Date.now() + ENDORSE_TIMEOUT_MS }),
    submitOptions: () => ({ deadline: Date.now() + SUBMIT_TIMEOUT_MS }),
    commitStatusOptions: () => ({ deadline: Date.now() + COMMIT_STATUS_TIMEOUT_MS }),
  });
  return cachedGateway;
}

export function getContract(): Contract {
  const config = cachedConfig ?? loadFabricConfigFromEnv();
  const gateway = getGateway(config);
  const network = gateway.getNetwork(config.channelName);
  return network.getContract(config.chaincodeName);
}

/** Cheap, non-network check used by GET /health — does NOT make a Fabric call. */
export function isGatewayConnected(): boolean {
  return cachedGateway !== undefined;
}

export function closeGateway(): void {
  cachedGateway?.close();
  cachedGrpcClient?.close();
  cachedGateway = undefined;
  cachedGrpcClient = undefined;
}
