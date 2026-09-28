import { useEffect, useState, type FormEvent } from "react";
import { listCentres, createCentre } from "../../../api/endpoints";
import { ApiError } from "../../../types/api";
import type { CentreResponse } from "../../../types/admin";
import { Button } from "../../../components/common/Button";
import { Input } from "../../../components/common/Input";
import { ErrorBanner } from "../../../components/common/ErrorBanner";
import { EmptyState } from "../../../components/common/EmptyState";
import { LoadingIndicator } from "../../../components/common/LoadingIndicator";

/**
 * GET/POST /api/v1/admin/centres (LLD 7.3 list, API-11 create) are
 * Admin-only and, as of Phase 6C, are real, database-backed
 * operations (backend/app/services/centre_service.py) instead of 501
 * stubs. Deactivating/renaming a centre uses the same PATCH endpoint
 * from a centre's detail context — this page focuses on the two
 * operations an Admin needs most often: seeing existing centres and
 * registering a new one.
 */
export function ExamCentresPage() {
  const [centres, setCentres] = useState<CentreResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [centreName, setCentreName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  function loadCentres() {
    setLoading(true);
    setLoadError(null);
    listCentres({ pageSize: 100 })
      .then((data) => setCentres(data.items))
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.userMessage : "Unable to load examination centres.");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadCentres();
  }, []);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setCreateError(null);

    const trimmed = centreName.trim();
    if (!trimmed) {
      setCreateError("Enter a centre name.");
      return;
    }

    setIsCreating(true);
    try {
      await createCentre({ centre_name: trimmed });
      setCentreName("");
      loadCentres();
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.userMessage : "Unable to create the examination centre.");
    } finally {
      setIsCreating(false);
    }
  }

  return (
    <div className="admin-page">
      <h1>Exam Centres</h1>

      <form className="lookup-form" onSubmit={handleCreate}>
        <Input
          id="centre-name"
          label="Register a new examination centre"
          placeholder="e.g. Greenview Examination Centre"
          value={centreName}
          onChange={(e) => setCentreName(e.target.value)}
        />
        <ErrorBanner message={createError} />
        <Button type="submit" isLoading={isCreating}>
          Register Centre
        </Button>
      </form>

      <h2 className="admin-section-heading">Examination centres</h2>
      {loading && <LoadingIndicator label="Loading examination centres…" />}
      {!loading && loadError && <ErrorBanner message={loadError} />}
      {!loading && !loadError && centres.length === 0 && (
        <EmptyState message="No examination centres registered yet." />
      )}
      {!loading && !loadError && centres.length > 0 && (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Centre ID</th>
              <th>Name</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {centres.map((centre) => (
              <tr key={centre.centre_id}>
                <td>{centre.centre_id}</td>
                <td>{centre.centre_name}</td>
                <td>
                  <span className="status-badge">{centre.is_active ? "Active" : "Inactive"}</span>
                </td>
                <td>{new Date(centre.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
