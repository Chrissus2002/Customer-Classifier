import { AppShell } from "../components/AppShell";
import { NotFoundState } from "../components/NotFoundState";

export function NotFoundPage() {
  return (
    <AppShell
      eyebrow="Error"
      title="Page not found"
      description="The page you requested does not exist."

    >
      <NotFoundState
        title="Unknown route"
        description="Return to journeys and continue from an existing workspace page."
      />
    </AppShell>
  );
}
