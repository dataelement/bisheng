import { useEffect,useState } from 'react';
export function useCitationMediaQuery(query:string) {
  const [matches,setMatches]=useState(()=>typeof window!=='undefined'&&typeof window.matchMedia==='function'&&window.matchMedia(query).matches);
  useEffect(()=>{
    if(typeof window.matchMedia!=='function')return;
    const media=window.matchMedia(query);const change=()=>setMatches(media.matches);
    change();media.addEventListener('change',change);return()=>media.removeEventListener('change',change);
  },[query]);
  return matches;
}
