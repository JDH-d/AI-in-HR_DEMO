import { Navigate, Route, Routes, useLocation } from "react-router";
import { lazy, Suspense } from "react";
import { useAuth } from "./providers";
import { LoginPage } from "../pages/LoginPage";
import { LoadingSkeleton } from "../components/ui";
import { useVisualViewport } from "./useVisualViewport";
const ChatPage = lazy(() => import("../features/chat/ChatPage").then(module => ({default: module.ChatPage})));
const EmployeeHome = lazy(() => import("../features/employee/EmployeeHome").then(module => ({default: module.EmployeeHome})));
const RequestsPage = lazy(() => import("../features/requests/RequestsPage").then(module => ({default: module.RequestsPage})));
const ManagerPage = lazy(() => import("../features/manager/ManagerPage").then(module => ({default: module.ManagerPage})));
const KnowledgePage = lazy(() => import("../features/knowledge-base/KnowledgePage").then(module => ({default: module.KnowledgePage})));

function Home() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === "employee" ? "/home" : user.role === "manager" ? "/manager" : "/knowledge"} replace />;
}
function LegacyChatRedirect() {
  const { user } = useAuth();
  const { search, hash } = useLocation();
  if (!user) return <Navigate to="/login" state={{ returnTo: `/employee${search}${hash}` }} replace />;
  // Preserve employees' old conversation links without exposing a chat screen
  // in the Manager or Knowledge Admin workspaces.
  return user?.role === "employee" ? <Navigate to={`/employee${search}${hash}`} replace /> : <Home/>;
}
export function App() {
  useVisualViewport();
  return <Suspense fallback={<LoadingSkeleton label="Opening workspace…" className="p-6"/>}><Routes><Route path="/" element={<Home/>}/><Route path="/login" element={<LoginPage/>}/>
    <Route path="/home" element={<Guard role="employee"><EmployeeHome/></Guard>}/>
    <Route path="/employee" element={<Guard role="employee"><ChatPage/></Guard>}/>
    <Route path="/chat" element={<LegacyChatRedirect/>}/>
    <Route path="/requests" element={<Guard role={["employee", "manager"]}><RequestsPage/></Guard>}/>
    <Route path="/manager" element={<Guard role="manager"><ManagerPage/></Guard>}/>
    <Route path="/knowledge" element={<Guard role="knowledge_admin"><KnowledgePage/></Guard>}/>
    <Route path="*" element={<Navigate to="/" replace />}/></Routes></Suspense>;
}
function Guard({ role, children }: { role?: string | string[]; children: React.ReactNode }) {
  const { user } = useAuth();
  const location = useLocation();
  const allowed = !role || (Array.isArray(role) ? role.includes(user?.role ?? "") : user?.role === role);
  return user && allowed ? children : <Navigate to="/login" state={{ returnTo: location.pathname + location.search + location.hash }} replace />;
}
