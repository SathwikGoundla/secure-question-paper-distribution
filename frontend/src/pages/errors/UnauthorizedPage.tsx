import { PageContainer } from "../../components/layout/PageContainer";

export function UnauthorizedPage() {
  return (
    <PageContainer>
      <div className="placeholder-card">
        <h1>Access denied</h1>
        <p>You do not have permission to view this page.</p>
      </div>
    </PageContainer>
  );
}
