import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router";
import { Shell } from "./Shell";

const auth = vi.hoisted(()=>({user:{role:"knowledge_admin",display_name:"Demo Admin"},logout:vi.fn()}));
vi.mock("../app/providers",()=>({useAuth:()=>auth}));
vi.mock("../features/integrations/PersonalNotifications",()=>({PersonalNotifications:()=>null}));
beforeEach(()=>{auth.user={role:"knowledge_admin",display_name:"Demo Admin"};});
afterEach(()=>{cleanup(); vi.unstubAllGlobals();});
function Page(){const location=useLocation(); return <Shell eyebrow="Admin"><h1>Workspace content</h1><p>{location.search}</p></Shell>;}

it("closes the mobile navigation after switching an admin section and exposes the selection",async()=>{
  render(<MemoryRouter initialEntries={["/knowledge?section=overview"]}><Page/></MemoryRouter>);
  const opener=screen.getByRole("button",{name:"Open menu"}); opener.focus(); fireEvent.click(opener);
  const dialog=await screen.findByRole("dialog",{name:"Workspace navigation"});
  fireEvent.click(within(dialog).getByRole("link",{name:"Documents"}));
  await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByRole("link",{name:"Documents"})).toHaveAttribute("aria-current","page");
  expect(screen.getByText("?section=documents")).toBeInTheDocument();
  expect(screen.getByRole("main")).toHaveFocus();
});
it("returns focus to the profile button after closing its dialog",async()=>{
  render(<MemoryRouter initialEntries={["/knowledge"]}><Page/></MemoryRouter>);
  const opener=screen.getByRole("button",{name:"Account and appearance"}); opener.focus(); fireEvent.click(opener);
  await screen.findByRole("dialog",{name:"Your account"});
  fireEvent.click(screen.getByRole("button",{name:"Close drawer"}));
  await waitFor(()=>expect(opener).toHaveFocus());
});
it("highlights Overview for an unsupported section and keeps role navigation separate",()=>{
  render(<MemoryRouter initialEntries={["/knowledge?section=unknown"]}><Page/></MemoryRouter>);
  expect(screen.getByRole("link",{name:"Overview"})).toHaveAttribute("aria-current","page");
  expect(screen.queryByRole("link",{name:"Review queue"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"Personal notifications"})).not.toBeInTheDocument();
});

it("releases the modal navigation when a mobile viewport becomes desktop",async()=>{
  let desktop=false;
  let changed: (()=>void) | undefined;
  vi.stubGlobal("matchMedia",(query:string)=>({
    get matches(){return query === "(min-width: 1024px)" && desktop;},
    addEventListener:(_event:string, listener:()=>void)=>{if(query === "(min-width: 1024px)") changed=listener;},
    removeEventListener:vi.fn(),
  }));
  render(<MemoryRouter initialEntries={["/knowledge"]}><Page/></MemoryRouter>);
  fireEvent.click(screen.getByRole("button",{name:"Open menu"}));
  await screen.findByRole("dialog",{name:"Workspace navigation"});
  expect(document.body.style.pointerEvents).toBe("none");
  act(()=>{desktop=true; changed?.();});
  await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(document.body.style.pointerEvents).not.toBe("none");
  await waitFor(()=>expect(screen.getByRole("main")).toHaveFocus());
  expect(screen.getByRole("link",{name:"Documents"})).toBeInTheDocument();
});

it("closes mobile navigation when the already selected section is chosen",async()=>{
  render(<MemoryRouter initialEntries={["/knowledge?section=documents"]}><Page/></MemoryRouter>);
  fireEvent.click(screen.getByRole("button",{name:"Open menu"}));
  const dialog=await screen.findByRole("dialog",{name:"Workspace navigation"});
  fireEvent.click(within(dialog).getByRole("link",{name:"Documents"}));
  await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByText("?section=documents")).toBeInTheDocument();
});

it("closes mobile navigation when the current conversation is chosen again",async()=>{
  auth.user={role:"employee",display_name:"Demo Employee"};
  render(<MemoryRouter initialEntries={["/employee?conversation=current"]}><Shell eyebrow="Chat" sidebar={<button aria-current="page">Current conversation</button>}><h1>Saved conversation</h1></Shell></MemoryRouter>);
  fireEvent.click(screen.getByRole("button",{name:"Open menu"}));
  const dialog=await screen.findByRole("dialog",{name:"Workspace navigation"});
  fireEvent.click(within(dialog).getByRole("button",{name:"Current conversation"}));
  await waitFor(()=>expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByRole("heading",{name:"Saved conversation"})).toBeInTheDocument();
});

it.each([
  ["manager", "/manager", "Review queue"],
  ["knowledge_admin", "/knowledge", "Overview"],
])("keeps bot chat out of %s desktop and mobile navigation",async(role,path,workspace)=>{
  auth.user={role,display_name:"Demo user"};
  render(<MemoryRouter initialEntries={[path]}><Page/></MemoryRouter>);
  expect(screen.getByRole("link",{name:workspace})).toBeInTheDocument();
  expect(screen.queryByRole("link",{name:"My chats"})).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button",{name:"Open menu"}));
  const dialog=await screen.findByRole("dialog",{name:"Workspace navigation"});
  expect(within(dialog).getByRole("link",{name:workspace})).toBeInTheDocument();
  expect(within(dialog).queryByRole("link",{name:"My chats"})).not.toBeInTheDocument();
});

it("keeps employee chats and requests in both navigation layouts",async()=>{
  auth.user={role:"employee",display_name:"Demo Employee"};
  render(<MemoryRouter initialEntries={["/employee"]}><Page/></MemoryRouter>);
  expect(screen.getByRole("link",{name:"My chats"})).toHaveAttribute("href","/employee");
  expect(screen.getByRole("link",{name:"My requests"})).toBeInTheDocument();
  expect(screen.getByRole("link",{name:"Home"})).toHaveAttribute("href","/home");
  fireEvent.click(screen.getByRole("button",{name:"Open menu"}));
  const dialog=await screen.findByRole("dialog",{name:"Workspace navigation"});
  expect(within(dialog).getByRole("link",{name:"My chats"})).toHaveAttribute("href","/employee");
  expect(within(dialog).getByRole("link",{name:"My requests"})).toBeInTheDocument();
  expect(within(dialog).getByRole("link",{name:"Home"})).toHaveAttribute("href","/home");
});

it("offers employee help without marking requests as active on Home",async()=>{
  auth.user={role:"employee",display_name:"Demo Employee"};
  render(<MemoryRouter initialEntries={["/home"]}><Page/></MemoryRouter>);
  expect(screen.getByRole("link",{name:"Home"})).toHaveAttribute("aria-current","page");
  expect(screen.getByRole("link",{name:"My requests"})).not.toHaveAttribute("aria-current");
  fireEvent.click(screen.getByRole("button",{name:"Employee help"}));
  const help=await screen.findByRole("dialog",{name:"Getting help"});
  expect(within(help).getByRole("button",{name:"Create a request"})).toBeInTheDocument();
});

it("keeps one scoped search and opens its history in the mobile navigation",async()=>{
  auth.user={role:"employee",display_name:"Demo Employee"};
  render(<MemoryRouter initialEntries={["/employee"]}><Shell eyebrow="Chat" sidebar={<p>Matching saved conversation</p>} headerContent={openNavigation => <><input aria-label="Search history"/><button onClick={openNavigation}>Show history</button></>}><h1>Chat</h1></Shell></MemoryRouter>);
  expect(screen.getAllByRole("textbox",{name:"Search history"})).toHaveLength(1);
  const opener=screen.getByRole("button",{name:"Show history"}); opener.focus(); fireEvent.click(opener);
  const dialog=await screen.findByRole("dialog",{name:"Workspace navigation"});
  expect(within(dialog).getByText("Matching saved conversation")).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole("button",{name:"Close menu"}));
  await waitFor(()=>expect(opener).toHaveFocus());
});
