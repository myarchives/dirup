from google.oauth2.service_account import Credentials
from googleapiclient.http import MediaFileUpload
import googleapiclient.discovery, argparse, pathlib, progress.bar, os

parser = argparse.ArgumentParser(description="tool to mass upload google drive files")
parser.add_argument("path", help="path to files")
parser.add_argument("dest", help="fileid destination to upload to")
parser.add_argument("--key", "-k", help="path to key file", required=False, default="key.json")
args = parser.parse_args()

creds = Credentials.from_service_account_file(args.key, scopes=[
    "https://www.googleapis.com/auth/drive"
])

drive = googleapiclient.discovery.build("drive", "v3", credentials=creds)

def ls(parent, searchTerms=""):
    files = []
    resp = drive.files().list(q=f"'{parent}' in parents" + searchTerms, pageSize=1000, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    files += resp["files"]
    while "nextPageToken" in resp:
        resp = drive.files().list(q=f"'{parent}' in parents" + searchTerms, pageSize=1000, supportsAllDrives=True, includeItemsFromAllDrives=True, pageToken=resp["nextPageToken"]).execute()
        files += resp["files"]
    return files

def lsd(parent):
    
    return ls(parent, searchTerms=" and mimeType contains 'application/vnd.google-apps.folder'")

def lsf(parent):
    
    return ls(parent, searchTerms=" and not mimeType contains 'application/vnd.google-apps.folder'")

def drive_path(path, parent):
    
    files = lsd(parent)
    for i in files:
        if i["name"] == path[0]:
            if len(path) == 1:
                return i["id"]
            else:
                return drive_path(path[1:], i["id"])
    resp = drive.files().create(body={
        "mimeType": "application/vnd.google-apps.folder",
        "name": path[0],
        "parents": [parent]
    }, supportsAllDrives=True).execute()
    if len(path) == 1:
        return resp["id"]
    else:
        return drive_path(path[1:], resp["id"])

def upload_resumable(filename, parent):
    
    media = MediaFileUpload(filename, resumable=True)
    request = drive.files().create(media_body=media, supportsAllDrives=True, body={
        "name": filename.split("/")[-1],    
        "parents": [parent]
    })
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print("Uploaded {:02.0f}%".format(status.progress()*100.0))

def upload_multipart(filename, parent):
    
    media = MediaFileUpload(filename)
    request = drive.files().create(media_body=media, supportsAllDrives=True, body={
        "name": filename.split("/")[-1],    
        "parents": [parent]
    }).execute()

files = [i for i in pathlib.Path(args.path).glob("**/*") if not i.is_dir()]
dirs_processed = []
pbar = progress.bar.Bar("processing files", max=len(files))
for i in files:
    file_path = i.as_posix()
    file_dir = "/".join(file_path.split("/")[:-1])
    
    flag = False
    for o in dirs_processed:
        if o[0] == file_dir:
            o[2].append(file_path)
            pbar.next()
            flag = True
            break
    if flag:
        continue
    dirs_processed.append([file_dir, drive_path(file_dir.split("/"), args.dest), [file_path]])
    pbar.next()
pbar.finish()

pbar = progress.bar.Bar("checking for dupes", max=len(dirs_processed))
deduped = []
for i in dirs_processed:
    dir_contents = lsf(i[1])
    dir_contents_paths = [i[0] + "/" + o["name"] for o in dir_contents]
    deduped.append([i[0], i[1], [x for x in i[2] if x not in dir_contents_paths]])
    pbar.next()
pbar.finish()

for i in deduped:
    for o in i[2]:
        print("uploading " + o)
        fsize = os.stat(o).st_size
        if fsize == 0: # if file empty, just create it
            drive.files().create(body={
                "name": o.split[-1],
                "parents": [i[1]]
            }, supportsAllDrives=True).execute()
        elif fsize <= 5120: # if file 5MB or lower use multipart upoad
            upload_multipart(o, i[1])
        else: # if files size above 5MB user resumable
            upload_resumable(o, i[1])