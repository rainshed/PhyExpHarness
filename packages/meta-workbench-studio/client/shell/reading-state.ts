import {useState} from 'react';
// Page reading state belongs to Studio. Saved state survives page unmounts only
// within this mounted workbench; no writes or changes to execution configuration.
export function useReadingState(initial:any,saved:any,onChange:any){
 const [local,setLocal]=useState(initial),value=saved??local;
 const update=(patch:any)=>onChange?onChange(patch):setLocal((old:any)=>({...old,...patch}));
 return [value,update];
}
