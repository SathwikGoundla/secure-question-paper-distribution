import { describe, it, expect, beforeEach, vi } from "vitest";
import { apiRequest, apiRequestBlob, setAuthToken, setUnauthorizedHandler } from "../api/client";
import { ApiError } from "../types/api";
import { jsonResponse, pdfResponse } from "../test/testUtils";

describe("apiRequest", () => {
  beforeEach(() => {
    setAuthToken(null);
    vi.restoreAllMocks();
  });

  it("uses the configured VITE_API_BASE_URL for every request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);

    await apiRequest("/auth/me");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const calledUrl = fetchMock.mock.calls[0][0] as string;
    expect(calledUrl).toBe("http://localhost:8000/api/v1/auth/me");
  });

  it("throws an ApiError with the backend's message on a 401 unauthorized response", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(401, {
        error: { message: "Session expired. Please log in again.", status_code: 401 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiRequest("/auth/me")).rejects.toMatchObject({
      userMessage: "Session expired. Please log in again.",
      status: 401,
    });
  });

  it("re-throws a generic, non-leaking message when the error body cannot be parsed", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    try {
      await apiRequest("/auth/me");
      expect.unreachable("apiRequest should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      const apiErr = err as ApiError;
      expect(apiErr.userMessage).not.toMatch(/Error|Traceback|Exception/);
      expect(apiErr.userMessage.length).toBeGreaterThan(0);
    }
  });

  it("attaches the Authorization header once a token has been set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {}));
    vi.stubGlobal("fetch", fetchMock);

    setAuthToken("test-token-123");
    await apiRequest("/auth/me");

    const options = fetchMock.mock.calls[0][1] as RequestInit;
    const headers = options.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer test-token-123");
  });
});

describe("Phase 6D — session-expiry handler and blob requests", () => {
  beforeEach(() => {
    setAuthToken(null);
    setUnauthorizedHandler(null);
    vi.restoreAllMocks();
  });

  it("notifies the handler when an authenticated request gets 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setAuthToken("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: "x", status_code: 401 } })));

    await expect(apiRequest("/auth/me")).rejects.toMatchObject({ status: 401 });
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does NOT notify the handler for a 401 on an unauthenticated call (bad credentials)", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    setAuthToken("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { error: { message: "x", status_code: 401 } })));

    await expect(apiRequest("/auth/login", { method: "POST", authenticated: false })).rejects.toMatchObject({ status: 401 });
    expect(handler).not.toHaveBeenCalled();
  });

  it("apiRequestBlob returns the PDF body and sends the bearer token", async () => {
    setAuthToken("tok");
    const fetchMock = vi.fn().mockResolvedValue(pdfResponse());
    vi.stubGlobal("fetch", fetchMock);

    const blob = await apiRequestBlob("/papers/p1/retrieve");
    expect(blob).toBeInstanceOf(Blob);
    expect((fetchMock.mock.calls[0][1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer tok" });
  });

  it("apiRequestBlob rejects a non-PDF success body", async () => {
    setAuthToken("tok");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(pdfResponse("application/json")));
    await expect(apiRequestBlob("/papers/p1/retrieve")).rejects.toBeInstanceOf(ApiError);
  });
});
