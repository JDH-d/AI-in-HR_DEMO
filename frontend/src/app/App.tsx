import { lazy, type ReactNode, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router";
import type { Role } from "../api/types";
import { LoginPage } from "../pages/LoginPage";
import { useAuth } from "./providers";

const EmployeePage = lazy(() =>
  import("../features/chat/EmployeePage").then((module) => ({ default: module.EmployeePage })),
);
const ManagerPage = lazy(() =>
  import("../features/manager/ManagerPage").then((module) => ({ default: module.ManagerPage })),
);
const KnowledgePage = lazy(() =>
  import("../features/knowledge-base/KnowledgePage").then((module) => ({
    default: module.KnowledgePage,
  })),
);

function Home() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  const destination =
    user.role === "employee" ? "/employee" : user.role === "manager" ? "/manager" : "/knowledge";
  return <Navigate to={destination} replace />;
}

export function App() {
  return (
    <Suspense fallback={<WorkspaceLoading />}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/employee"
          element={
            <Guard requiredRole="employee">
              <EmployeePage />
            </Guard>
          }
        />
        <Route
          path="/manager"
          element={
            <Guard requiredRole="manager">
              <ManagerPage />
            </Guard>
          }
        />
        <Route
          path="/knowledge"
          element={
            <Guard requiredRole="knowledge_admin">
              <KnowledgePage />
            </Guard>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}

function Guard({ requiredRole, children }: { requiredRole: Role; children: ReactNode }) {
  const { user } = useAuth();
  return user?.role === requiredRole ? children : <Navigate to="/login" replace />;
}

function WorkspaceLoading() {
  return (
    <main className="grid min-h-screen place-items-center text-sm text-muted" role="status">
      Opening workspace…
    </main>
  );
}
