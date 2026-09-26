import { Link } from "react-router-dom";
import { PageContainer } from "../../components/layout/PageContainer";

export function NotFoundPage() {
  return (
    <PageContainer>
      <div className="placeholder-card">
        <h1>Page not found</h1>
        <p>The page you are looking for does not exist.</p>
        <Link to="/">Return to the start page</Link>
      </div>
    </PageContainer>
  );
}
