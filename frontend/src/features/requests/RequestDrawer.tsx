import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarDays, Check, Clock3, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { WorkflowRequest } from "../../api/types";
import { useAuth } from "../../app/providers";
import { Badge, Button, Card, Drawer, fieldClass, statusTone } from "../../components/ui";

export function RequestDrawer({ open, onOpenChange, initial }: { open: boolean; onOpenChange: (v:boolean)=>void; initial?: WorkflowRequest | null }) {
  const { token }=useAuth(); const qc=useQueryClient();
  const [type,setType]=useState("pto"); const [start,setStart]=useState(""); const [end,setEnd]=useState(""); const [comment,setComment]=useState(""); const [approver,setApprover]=useState("manager.demo"); const [error,setError]=useState("");
  useEffect(()=>{ if(initial){setType(initial.type);setStart(initial.start_date??"");setEnd(initial.end_date??"");setComment(initial.comment);setApprover(initial.approver||"manager.demo");}},[initial]);
  const mutation=useMutation({mutationFn:async()=>{
    let request=initial;
    if(!request){const created=await api<{request:WorkflowRequest}>("/api/v1/requests",token,{method:"POST",body:JSON.stringify({type,start_date:start||null,end_date:end||null,comment,approver})});request=created.request;}
    return api<{request:WorkflowRequest}>(`/api/v1/requests/${request.id}/submit`,token,{method:"POST",body:JSON.stringify({type,start_date:start||null,end_date:end||null,comment,approver})});
  },onSuccess:()=>{qc.invalidateQueries({queryKey:["requests"]});onOpenChange(false);},onError:e=>setError(e instanceof Error?e.message:"Unable to submit")});
  const duration=start&&end?Math.max(1,Math.round((new Date(end).getTime()-new Date(start).getTime())/86400000)+1):null;
  return <Drawer open={open} onOpenChange={onOpenChange} title={initial?"Review request":"Create request"} description="Nothing is sent until you confirm. Every later decision is added to the timeline.">
    <div className="mb-6 flex items-center justify-between"><Badge tone={statusTone(initial?.status??"draft")}>{initial?.status??"new draft"}</Badge><span className="text-xs text-muted">Required fields marked *</span></div>
    <div className="space-y-5"><label className="block text-xs font-semibold text-muted">Request type *<select className={`${fieldClass} mt-2`} value={type} onChange={e=>setType(e.target.value)}><option value="pto">Vacation / PTO</option><option value="sick_leave">Sick leave</option><option value="document">Document request</option></select></label>
    <div className="grid grid-cols-2 gap-3"><label className="text-xs font-semibold text-muted">Starts *<input className={`${fieldClass} mt-2`} type="date" value={start} onChange={e=>setStart(e.target.value)}/></label><label className="text-xs font-semibold text-muted">Ends *<input className={`${fieldClass} mt-2`} type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label></div>
    <label className="block text-xs font-semibold text-muted">What should your manager know? *<textarea className={`${fieldClass} mt-2 min-h-28 resize-none`} value={comment} onChange={e=>setComment(e.target.value)} placeholder="Add useful context, not a formal essay."/></label>
    <label className="block text-xs font-semibold text-muted">Approver<input className={`${fieldClass} mt-2`} value={approver} onChange={e=>setApprover(e.target.value)}/></label>
    <Card className="grid grid-cols-2 gap-4 bg-ink/50 p-4 text-xs"><Summary icon={<CalendarDays size={16}/>} label="Period" value={start&&end?`${start} → ${end}`:"Not set"}/><Summary icon={<Clock3 size={16}/>} label="Duration" value={duration?`${duration} day${duration===1?"":"s"}`:"—"}/><Summary icon={<UserRound size={16}/>} label="Applicant" value="You"/><Summary icon={<Check size={16}/>} label="Next status" value="Submitted"/></Card>
    {error&&<p className="rounded-xl bg-danger/10 p-3 text-sm text-danger">{error}</p>}<div className="flex gap-3"><Button tone="secondary" className="flex-1" onClick={()=>onOpenChange(false)}>Keep as draft</Button><Button className="flex-1" disabled={mutation.isPending||!comment} onClick={()=>mutation.mutate()}>{mutation.isPending?"Submitting…":"Submit request"}</Button></div></div>
  </Drawer>;
}
function Summary({icon,label,value}:{icon:React.ReactNode;label:string;value:string}){return <div className="flex gap-2 text-muted"><span className="text-lime">{icon}</span><div><span className="block text-[10px] uppercase tracking-wider">{label}</span><strong className="mt-1 block text-cream">{value}</strong></div></div>}
