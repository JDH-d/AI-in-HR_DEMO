import { ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../app/providers";
import { Hint } from "../../components/ui";
export function FeedbackButtons({question}:{question:string}){const{token}=useAuth();const[done,setDone]=useState<number|null>(null);const send=async(rating:number)=>{await api("/api/v1/feedback",token,{method:"POST",body:JSON.stringify({rating,question})});setDone(rating)};return <div className="flex items-center gap-1"><Hint label="Helpful"><button aria-label="Helpful" onClick={()=>send(5)} className={`rounded-lg p-2 ${done===5?"bg-lime-soft text-lime":"text-muted hover:text-cream"}`}><ThumbsUp size={15}/></button></Hint><Hint label="Needs work"><button aria-label="Not helpful" onClick={()=>send(1)} className={`rounded-lg p-2 ${done===1?"bg-danger/10 text-danger":"text-muted hover:text-cream"}`}><ThumbsDown size={15}/></button></Hint></div>}
