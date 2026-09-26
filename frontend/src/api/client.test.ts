import { describe, it, expect, beforeEach, vi } from "vitest";
import { apiRequest, setAuthToken } from "../api/client";
import { ApiError } from "../types/api";
import { jsonResponse } from "../test/testUtils";

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
