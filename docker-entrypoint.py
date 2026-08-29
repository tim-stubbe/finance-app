#!/usr/bin/env python3
"""Container-Einstieg: startet kurz als root, sorgt dafuer dass /data dem
unprivilegierten `app`-User gehoert, und laesst dann PERMANENT die Rechte
fallen, bevor uvicorn ausgefuehrt wird (Security-Hardening L-01).

Warum ein Python-Shim statt `USER app` im Dockerfile: `/data` ist ein
Volume/Bind-Mount und gehoert auf dem Host oft root. Ein fest gesetzter
`USER app` koennte dann nicht hineinschreiben und die App faellt beim Start
um. Dieser Shim chownt `/data` einmalig (nur wenn noetig) und wechselt
danach zu uid 1000 - `python:slim` bringt kein gosu/setpriv mit, os.setuid
reicht aber vollstaendig.

Laeuft der Container bereits unprivilegiert (z.B. `docker run --user`), wird
der ganze Block uebersprungen und direkt exec't.
"""
import os
import pwd
import sys


def _drop_privileges() -> None:
    if os.geteuid() != 0:
        return  # schon unprivilegiert - nichts zu tun

    try:
        app = pwd.getpwnam("app")
    except KeyError:
        print("entrypoint: kein 'app'-User im Image - laufe als root weiter", file=sys.stderr)
        return

    data_dir = os.environ.get("DATA_DIR", "/data")
    try:
        os.makedirs(data_dir, exist_ok=True)
        if os.stat(data_dir).st_uid != app.pw_uid:
            # Nur wenn der Top-Ordner noch nicht dem app-User gehoert -
            # sonst bei jedem Neustart rekursiv ueber ggf. GBs an Fotos/
            # Backups/Voice-Modellen zu laufen.
            for root, dirs, files in os.walk(data_dir):
                os.chown(root, app.pw_uid, app.pw_gid)
                for name in files:
                    path = os.path.join(root, name)
                    if not os.path.islink(path):
                        os.chown(path, app.pw_uid, app.pw_gid)
    except OSError as exc:
        print(f"entrypoint: konnte {data_dir} nicht anpassen ({exc}) - fahre fort", file=sys.stderr)

    os.setgid(app.pw_gid)
    try:
        os.initgroups(app.pw_name, app.pw_gid)
    except OSError:
        pass
    os.setuid(app.pw_uid)
    os.environ["HOME"] = app.pw_dir


def main() -> None:
    _drop_privileges()
    if len(sys.argv) < 2:
        print("entrypoint: kein Kommando angegeben", file=sys.stderr)
        raise SystemExit(2)
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
