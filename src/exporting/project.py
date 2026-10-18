"""Export exactly the tested Bundle, never regenerate execution code."""
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from src.execution.bundle.freeze import verify, digest


def export_project(bundle_root, destination):
    bundle_root, destination = Path(bundle_root), Path(destination)
    bundle = verify(bundle_root)
    export_id = 'export-' + str(uuid.uuid4())
    folder = destination / export_id
    project = folder / 'harness'
    project.mkdir(parents=True)
    for relative in [*bundle['files'], 'bundle.json']:
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle_root / relative, target)
    verify(project)
    archive = folder / 'harness.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for file in sorted(project.rglob('*')):
            if file.is_file(): z.write(file, 'harness/' + str(file.relative_to(project)))
    record = {'schemaVersion':1,'id':export_id,'candidateId':bundle['id'],'bundleId':bundle['id'],
        'path':str(project),'archive':str(archive),'archiveSha256':digest(archive.read_bytes()),
        'staticValidation':'passed','relocationValidation':'not_run','realValidation':'not_run',
        'files':sorted(bundle['files']),'dependencies':json.loads((project/'package.json').read_text())['dependencies']}
    (folder/'export.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    return record
