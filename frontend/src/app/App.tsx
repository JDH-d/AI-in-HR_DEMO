import { Navigate, Route, Routes } from "react-router";
import { useAuth } from "./providers";
import { LoginPage } from "../pages/LoginPage";
import { EmployeePage } from "../features/chat/EmployeePage";
import { ManagerPage } from "../features/manager/ManagerPage";
import { KnowledgePage } from "../features/knowledge-base/KnowledgePage";

function Home() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === "employee" ? "/employee" : user.role === "manager" ? "/manager" : "/knowledge"} replace />;
}
export function App() {
  return <Routes><Route path="/" element={<Home/>}/><Route path="/login" element={<LoginPage/>}/>
    <Route path="/employee" element={<Guard role="employee"><EmployeePage/></Guard>}/>
    <Route path="/manager" element={<Guard role="manager"><ManagerPage/></Guard>}/>
    <Route path="/knowledge" element={<Guard role="knowledge_admin"><KnowledgePage/></Guard>}/>
    <Route path="*" element={<Navigate to="/" replace />}/></Routes>;
}
function Guard({ role, children }: { role: string; children: React.ReactNode }) {
  const { user } = useAuth();
  return user?.role === role ? children : <Navigate to="/login" replace />;
}
