// Navigation only: a link never creates, starts, resumes or modifies an activity.
export function entryCampaign(hash){
 if(hash==='#phyexp')return '';
 const match=/^#phyexp\/([a-zA-Z0-9_-]{1,200})$/.exec(hash||'');
 return match?match[1]:null;
}
