import { PageContainer } from "../../components/layout/PageContainer";

interface PlaceholderPageProps {
  title: string;
  phaseNote: string;
}

/**
 * Explicitly a placeholder — no fake dashboard, charts, or data.
 * Phase 6A's brief is clear that this phase must not implement the
 * Admin or Exam Centre dashboards; this component makes that boundary
 * visible in the running app rather than silently rendering nothing.
 */
export function PlaceholderPage({ title, phaseNote }: PlaceholderPageProps) {
  return (
    <PageContainer>
      <div className="placeholder-card">
        <h1>{title}</h1>
        <p>{phaseNote}</p>
      </div>
    </PageContainer>
  );
}
