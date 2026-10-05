"""Local report drafts, scoped to server, account and order; no credentials."""
import hashlib,json,os,math
from pathlib import Path


class ReportDraft:
    def __init__(self,store,user,task_id):
        if hasattr(store,'path'):base=Path(store.path).parent
        else:
            from PySide6.QtCore import QStandardPaths
            base=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        scope=hashlib.sha256(str(getattr(store,'url','local')).encode()).hexdigest()[:16]
        self.directory=base/'drafts'/scope/str(user['id'])
        self.path=self.directory/f'{int(task_id)}.json'
    def load(self):
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(value,dict):return {}
            clean={key:value[key] for key in ('work','result','defect') if isinstance(value.get(key),str)}
            hours=value.get('hours')
            if isinstance(hours,(int,float)) and not isinstance(hours,bool) and math.isfinite(hours) and .1<=hours<=24:clean['hours']=hours
            clean['materials']=[{key:str(item.get(key,'')) for key in ('name','quantity','unit','price')}
                for item in value.get('materials',[]) if isinstance(item,dict)] if isinstance(value.get('materials'),list) else []
            clean['photo_sources']=[p for p in value.get('photo_sources',[]) if isinstance(p,str)][:5] if isinstance(value.get('photo_sources'),list) else []
            return clean
        except (OSError,ValueError):return {}
    def save(self,value):
        self.directory.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.pending')
        temporary.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        os.replace(temporary,self.path)
    def clear(self):self.path.unlink(missing_ok=True)


def clear_user_drafts(store,user):
    draft=ReportDraft(store,user,0)
    if draft.directory.is_dir():
        error=None
        for path in draft.directory.iterdir():
            if path.suffix not in ('.json','.pending') or not path.is_file():continue
            try:path.unlink(missing_ok=True)
            except OSError as exc:error=exc
        if error:raise error
