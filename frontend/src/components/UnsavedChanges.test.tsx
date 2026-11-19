import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { createMemoryRouter, Link, Outlet, RouterProvider, useLocation, useNavigate } from "react-router";
import { useState } from "react";
import { UnsavedChangesProvider, useProtectedNavigation, useUnsavedChanges } from "./UnsavedChanges";

afterEach(cleanup);
function Form() {
  const [value, setValue] = useState("");
  const clear = useUnsavedChanges(Boolean(value));
  const protect = useProtectedNavigation();
  const navigate = useNavigate();
  return <><label>Draft<input value={value} onChange={event => setValue(event.target.value)}/></label>
    <Link to="/other">Other section</Link>
    <button onClick={() => navigate(-1)}>Browser back</button>
    <button onClick={() => { clear(); navigate("/other"); }}>Save and close</button>
    <button onClick={() => protect(() => navigate("/other"))}>Sign out</button>
  </>;
}
function App() { const location = useLocation(); return <UnsavedChangesProvider><p>Location: {location.pathname}</p><Outlet/></UnsavedChangesProvider>; }
function mount() {
  const router = createMemoryRouter([{element:<App/>,children:[{path:"/form",element:<Form/>},{path:"/other",element:<p>Other page</p>}]}],{initialEntries:["/other","/form"],initialIndex:1});
  render(<RouterProvider router={router}/>);
  fireEvent.change(screen.getByLabelText("Draft"),{target:{value:"Keep my work"}});
  return router;
}
it("keeps form content when navigation is cancelled and discards only after confirmation", async () => {
  const router = mount();
  fireEvent.click(screen.getByRole("link",{name:"Other section"}));
  await screen.findByRole("dialog",{name:"Leave without saving?"});
  fireEvent.click(screen.getByRole("button",{name:"Keep editing"}));
  expect(screen.getByLabelText("Draft")).toHaveValue("Keep my work");
  expect(router.state.location.pathname).toBe("/form");
  fireEvent.click(screen.getByRole("link",{name:"Other section"}));
  fireEvent.click(await screen.findByRole("button",{name:"Discard changes and leave"}));
  await screen.findByText("Other page");
});
it("protects history-back navigation", async () => {
  const router = mount();
  fireEvent.click(screen.getByRole("button",{name:"Browser back"}));
  await screen.findByRole("dialog",{name:"Leave without saving?"});
  expect(router.state.location.pathname).toBe("/form");
  fireEvent.click(screen.getByRole("button",{name:"Keep editing"}));
  expect(screen.getByLabelText("Draft")).toHaveValue("Keep my work");
});
it("does not ask twice when an explicitly confirmed action navigates", async () => {
  mount();
  fireEvent.click(screen.getByRole("button",{name:"Sign out"}));
  fireEvent.click(await screen.findByRole("button",{name:"Discard changes and leave"}));
  await screen.findByText("Other page");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("synchronously clears the guard after a successful save", async () => {
  mount();
  fireEvent.click(screen.getByRole("button",{name:"Save and close"}));
  await screen.findByText("Other page");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("registers unload protection only while the form is dirty", async () => {
  mount();
  const event = new Event("beforeunload",{cancelable:true});
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  fireEvent.change(screen.getByLabelText("Draft"),{target:{value:""}});
  const clean = new Event("beforeunload",{cancelable:true});
  window.dispatchEvent(clean);
  expect(clean.defaultPrevented).toBe(false);
});
it("protects explicit actions and does not run them on cancellation", async () => {
  const action = vi.fn();
  function Probe() { useUnsavedChanges(true); const protect=useProtectedNavigation(); return <button onClick={()=>protect(action)}>Protected action</button>; }
  render(<UnsavedChangesProvider><Probe/></UnsavedChangesProvider>);
  fireEvent.click(screen.getByRole("button",{name:"Protected action"}));
  fireEvent.click(await screen.findByRole("button",{name:"Keep editing"}));
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button",{name:"Protected action"}));
  fireEvent.click(screen.getByRole("button",{name:"Discard changes and leave"}));
  await waitFor(()=>expect(action).toHaveBeenCalledTimes(1));
});

it("keeps other dirty forms protected when a confirmed asynchronous action fails", async () => {
  let fail!: (error: Error) => void;
  const operation = new Promise<void>((_resolve,reject)=>{fail=reject;});
  function Forms() {
    const [comment,setComment]=useState("Unsent feedback");
    const [draft,setDraft]=useState("Unsent chat draft");
    useUnsavedChanges(Boolean(comment));
    useUnsavedChanges(Boolean(draft));
    const protect=useProtectedNavigation();
    return <><label>Feedback<input value={comment} onChange={event=>setComment(event.target.value)}/></label>
      <label>Message<input value={draft} onChange={event=>setDraft(event.target.value)}/></label>
      <button onClick={()=>protect(()=>operation)}>New conversation</button><Link to="/other">Leave</Link></>;
  }
  const router=createMemoryRouter([{element:<App/>,children:[{path:"/form",element:<Forms/>},{path:"/other",element:<p>Other page</p>}]}],{initialEntries:["/form"]});
  render(<RouterProvider router={router}/>);
  fireEvent.click(screen.getByRole("button",{name:"New conversation"}));
  fireEvent.click(await screen.findByRole("button",{name:"Discard changes and leave"}));
  await act(async()=>{fail(new Error("Create failed")); await Promise.resolve();});
  expect(screen.getByLabelText("Feedback")).toHaveValue("Unsent feedback");
  const event=new Event("beforeunload",{cancelable:true}); window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  fireEvent.click(screen.getByRole("link",{name:"Leave"}));
  await screen.findByRole("dialog",{name:"Leave without saving?"});
  expect(router.state.location.pathname).toBe("/form");
});

it("does not ask a second time when a confirmed async action finishes by navigating",async()=>{
  let complete!: ()=>void;
  const operation=new Promise<void>(resolve=>{complete=resolve;});
  function AsyncForm(){
    useUnsavedChanges(true);
    const protect=useProtectedNavigation(); const navigate=useNavigate();
    return <button onClick={()=>protect(async()=>{await operation; navigate("/other");})}>Create and open</button>;
  }
  const router=createMemoryRouter([{element:<App/>,children:[{path:"/form",element:<AsyncForm/>},{path:"/other",element:<p>Other page</p>}]}],{initialEntries:["/form"]});
  render(<RouterProvider router={router}/>);
  fireEvent.click(screen.getByRole("button",{name:"Create and open"}));
  fireEvent.click(await screen.findByRole("button",{name:"Discard changes and leave"}));
  await act(async()=>{complete(); await operation;});
  await screen.findByText("Other page");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
