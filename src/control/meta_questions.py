"""Durable questions; only the authenticated human endpoint can answer."""
import hashlib
from .store import Refused,Conflict,encoded

def request(store,session_id,agent_id,call_id,questions):
    with store.connection(True) as db:
        session=store._get(db,'meta_sessions',session_id)
        if session.get('runtimeVersion')!='meta-runtime-v2' or session.get('nativeSessionId')!=agent_id:
            raise Refused('Only the native main Meta may ask the user')
        if not isinstance(call_id,str) or not call_id or len(call_id)>200:raise Refused('Invalid question identity')
        if not isinstance(questions,list) or not 1<=len(questions)<=10:raise Refused('Invalid questions')
        ids=set()
        for q in questions:
            if not isinstance(q,dict) or not isinstance(q.get('id'),str) or q['id'] in ids or not isinstance(q.get('question'),str) or not q['question'].strip():raise Refused('Invalid question')
            ids.add(q['id'])
        if len(encoded(questions))>32000:raise Refused('Questions too long')
        id='question-'+hashlib.sha256(encoded([session['campaignId'],agent_id,call_id]).encode()).hexdigest()
        existing=next((q for q in store._list(db,'meta_questions',session['campaignId']) if q['id']==id),None)
        if existing:
            if existing['questions']!=questions:raise Conflict('Question identity conflict')
            return existing
        row=store._save(db,'meta_questions',{'id':id,'campaignId':session['campaignId'],'sessionId':session_id,'agentId':agent_id,'callId':call_id,'questions':questions,'state':'pending','createdAt':store.clock()})
        store._event(db,session['campaignId'],'meta_question',questionId=id)
        return row

def answer(store,id,value):
    with store.connection(True) as db:
        row=store._get(db,'meta_questions',id);c=store._get(db,'campaigns',row['campaignId'])
        if c['state'] in ['finished','failed']:raise Refused('Activity has ended')
        answers=value.get('answers')
        if not isinstance(answers,list) or len(answers)!=len(row['questions']):raise Refused('Answer every question, or explicitly leave it empty')
        if any(not isinstance(a,dict) for a in answers) or {a.get('id') for a in answers}!={q['id'] for q in row['questions']}:raise Refused('Answer identities mismatch')
        for a in answers:
            q=next(q for q in row['questions'] if q['id']==a['id']);selected=a.get('selected')
            if not isinstance(selected,list) or any(not isinstance(x,str) for x in selected) or len(set(selected))!=len(selected):raise Refused('Invalid selected answers')
            if set(selected)-{o['label'] for o in q.get('options',[])} or (len(selected)>1 and not q.get('multiSelect')):raise Refused('Invalid answer options')
            if not isinstance(a.get('custom',''),str) or len(a.get('custom',''))>16000:raise Refused('Invalid free-text answer')
        clean={'answers':[{k:v for k,v in a.items() if k in ['id','selected','custom']} for a in answers]}
        if row['state']=='answered':
            if row['answer']!=clean:raise Conflict('Question already answered differently')
            return row
        row=store._save(db,'meta_questions',{**row,'state':'answered','answer':clean,'answeredAt':store.clock()})
        store._event(db,row['campaignId'],'meta_question_answered',questionId=id,questions=row['questions'],answer=clean)
        return row
