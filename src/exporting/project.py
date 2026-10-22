"""Export exactly the tested Bundle, never regenerate execution code."""
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from src.execution.bundle.manifest import resolve, verify, digest, canonical


def export_project(bundle_root, destination):
    bundle_root, destination = Path(bundle_root), Path(destination)
    resolved = resolve(bundle_root)
    bundle = resolved.manifest
    export_id = 'export-' + str(uuid.uuid4())
    folder = destination / export_id
    project = folder / 'harness'
    project.mkdir(parents=True)
    for relative, source in {**resolved.assets, 'bundle.json': bundle_root / 'bundle.json'}.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    if bundle.get('schemaVersion') == 2:
        (project / 'objects.json').write_bytes(canonical(resolved.objects) + b'\n')
    exported = verify(project)
    archive = folder / 'harness.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for file in sorted(project.rglob('*')):
            if file.is_file(): z.write(file, 'harness/' + str(file.relative_to(project)))
    record = {'schemaVersion':1,'id':export_id,'candidateId':bundle['id'],'bundleId':bundle['id'],
        'exporter':{'format':'plugin-project-v2' if bundle.get('schemaVersion')==2 else 'legacy-bundle-v1',
                    'implementationSha256':digest(Path(__file__).read_bytes())},
        'path':str(project),'archive':str(archive),'archiveSha256':digest(archive.read_bytes()),
        'staticValidation':'passed','relocationValidation':'not_run','realValidation':'not_run',
        'files':sorted(exported['files']),'dependencies':json.loads((project/'package.json').read_text())['dependencies']}
    if bundle.get('schemaVersion') == 2:
        record.update(compositionId=bundle['id'], framework=bundle['framework'])
    (folder/'export.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    return record
