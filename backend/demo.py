"""Explicit, idempotent demo data. Never inferred or mixed into real memory extraction."""
import time
from .db import DB, Message, User, get, put, migrate
from .memory import save_memory

def main():
    migrate()
    with DB() as db:
        if get(db, 'demo', 1, 'seeded'):
            print('Demo already seeded.')
            return
        users={u.username:u.id for u in db.query(User).all()}
        lines=[('mom','【演示】周六一起吃饭吧，小宇有空吗？'),('dad','【演示】我来买菜，妈妈最近喜欢清淡一点。'),('child','【演示】下午有课，晚上可以。')]
        ids=[]
        for i,(login,content) in enumerate(lines):
            m=Message(group_id=1,user_id=users[login],client_id='demo:'+str(i),content=content,created=time.time()-600+i*60,attachments='[]')
            db.add(m);db.flush();ids.append(m.id)
        db.add(Message(group_id=1,user_id=0,client_id='demo:agent',content='【演示】我记得妈妈喜欢清淡口味，需要我帮忙整理菜单吗？',created=time.time()-350,attachments='[]'))
        save_memory(db,1,'【演示】妈妈喜欢清淡口味',[ids[1]],['妈妈'],key='demo-taste',manual=True)
        save_memory(db,1,'【演示】每周六家庭聚餐',[],key='demo-dinner',manual=True)
        put(db,'task',1,'demo-task',{'title':'【演示】周六晚餐准备','owner_id':users['dad'],'due':None,'done':False})
        put(db,'demo',1,'seeded',{'at':time.time()})
        db.commit()
    print('Labeled demo data created. No agent analysis jobs were scheduled.')

if __name__=='__main__': main()
