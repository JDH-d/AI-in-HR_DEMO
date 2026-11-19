import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "./App";

const auth=vi.hoisted(()=>({user:null as {role:string}|null}));
vi.mock("./providers",()=>({useAuth:()=>auth}));
vi.mock("../pages/LoginPage",()=>({LoginPage:()=> <h1>Sign in</h1>}));
vi.mock("../features/chat/ChatPage",()=>({ChatPage:()=> <h1>Employee bot chat</h1>}));
vi.mock("../features/employee/EmployeeHome",()=>({EmployeeHome:()=> <h1>Employee home</h1>}));
vi.mock("../features/manager/ManagerPage",()=>({ManagerPage:()=> <h1>Manager request queue</h1>}));
vi.mock("../features/knowledge-base/KnowledgePage",()=>({KnowledgePage:()=> <h1>Knowledge administration</h1>}));

function Location(){const location=useLocation(); return <p data-testid="location">{location.pathname+location.search+location.hash}</p>;}
function mount(path:string){render(<MemoryRouter initialEntries={[path]}><App/><Location/></MemoryRouter>);}
beforeEach(()=>{auth.user=null;});
afterEach(cleanup);

it.each([
  ["manager","Manager request queue","/manager"],
  ["knowledge_admin","Knowledge administration","/knowledge"],
])("redirects old chat links for %s without mounting the bot workspace",async(role,heading,path)=>{
  auth.user={role};
  mount("/chat?conversation=existing-history#latest");
  expect(await screen.findByRole("heading",{name:heading})).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent(path);
  expect(screen.queryByRole("heading",{name:"Employee bot chat"})).not.toBeInTheDocument();
});

it("preserves an employee's saved conversation when opening the old chat address",async()=>{
  auth.user={role:"employee"};
  mount("/chat?conversation=existing-history#latest");
  expect(await screen.findByRole("heading",{name:"Employee bot chat"})).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/employee?conversation=existing-history#latest");
});

it("requires sign-in for old chat addresses",async()=>{
  mount("/chat?conversation=existing-history");
  expect(await screen.findByRole("heading",{name:"Sign in"})).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"Employee bot chat"})).not.toBeInTheDocument();
});

it.each(["manager","knowledge_admin"])("does not expose employee chat through /employee to %s",async role=>{
  auth.user={role};
  mount("/employee?conversation=existing-history");
  expect(await screen.findByRole("heading",{name:"Sign in"})).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"Employee bot chat"})).not.toBeInTheDocument();
});

it("opens the employee task homepage by default while keeping saved chats separate",async()=>{
  auth.user={role:"employee"};
  mount("/");
  expect(await screen.findByRole("heading",{name:"Employee home"})).toBeInTheDocument();
  expect(screen.getByTestId("location")).toHaveTextContent("/home");
  expect(screen.queryByRole("heading",{name:"Employee bot chat"})).not.toBeInTheDocument();
});

it.each(["manager","knowledge_admin"])("does not mount employee tasks for %s",async role=>{
  auth.user={role};
  mount("/home");
  expect(await screen.findByRole("heading",{name:"Sign in"})).toBeInTheDocument();
  expect(screen.queryByRole("heading",{name:"Employee home"})).not.toBeInTheDocument();
});
