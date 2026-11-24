import { Navigate, Route, Routes } from "react-router-dom";
import { ContactInspectorPage } from "./pages/ContactInspectorPage";
import { JourneyListPage } from "./pages/JourneyListPage";
import { JourneyStudioPage } from "./pages/JourneyStudioPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { routes } from "./routes";

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={routes.journeys} replace />} />
      <Route path={routes.journeys} element={<JourneyListPage />} />
      <Route path="/journeys/:journeyKey" element={<JourneyStudioPage />} />
      <Route path="/contacts/:contactId" element={<ContactInspectorPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}

export default App;
