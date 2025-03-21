import contextlib
import io
import json
import os, sys, requests, subprocess
import random
import re
import string
import time

import yaml


def call(cmd, input=None):
    print()
    print()
    print(cmd)
    process = subprocess.Popen(cmd, text=True,
                               stdin=subprocess.PIPE if input else subprocess.DEVNULL,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT,
                               )
    d = process.communicate(input=input)[0]
    d = (process.poll(), d)
    print(d)
    return d


def init():
    # 安装和配置lxc
    d = call([
        "apt", "update", "-y",
    ], )
    if d[0] != 0:
        print("更新包列表失败", )
        sys.exit(1)

    d = call([
        "apt", "upgrade", "-y",
    ], )
    if d[0] != 0:
        print("更新包失败", )
        sys.exit(1)

    d = call([
        "apt", "install", "lxd", "-y",
    ], )
    if d[0] != 0:
        print("安装lxd失败", )
        sys.exit(1)

    d = call([
        "apt", "install", "btrfs-progs", "-y",
    ], )
    if d[0] != 0:
        print("安装btrfs-progs失败", )
        sys.exit(1)

    d = call([
        "lxc", "remote", "set-url", "images", "https://images.lxd.canonical.com",
    ], )
    if d[0] != 0:
        print("修改镜像拉取地址失败", )
        sys.exit(1)

    if True:
        d = call([
            "lxc", "profile", "show", "default",
        ], )
        if d[0] != 0:
            print("获取lxc默认配置文件失败", )
            sys.exit(1)

        y = yaml.safe_load(io.StringIO(d[1]))
        print(y)
        y["devices"].pop("root", None)
        print(y)
        # del y["devices"]["root"]
        # y["devices"]["root"]["size"] = "1GB"
        s = io.StringIO()
        yaml.safe_dump(y, s)

        d = call(
            ["lxc", "profile", "edit", "default", ], input=s.getvalue(),
        )
        if d[0] != 0:
            print("修改lxc默认配置文件失败", )
            sys.exit(1)

    d = call([
        "lxc", "storage", "delete", "default",
    ], )
    if d[0] != 0:
        print("删除储存池失败", )
        # sys.exit(1)

    d = call([
        "lxc", "storage", "create", "default", "btrfs", f"size={_disk_size}GB",
    ], )
    if d[0] != 0:
        print("创建储存池失败", )
        sys.exit(1)

    if True:
        d = call([
            "lxc", "profile", "show", "default",
        ], )
        if d[0] != 0:
            print("获取lxc默认配置文件失败", )
            sys.exit(1)

        y = yaml.safe_load(io.StringIO(d[1]))
        print(y)
        y["devices"]["root"] = {
            "path": "/",
            "pool": "default",
            # "size": "1GB",
            "type": "disk",
        }
        print(y)
        # del y["devices"]["root"]
        # y["devices"]["root"]["size"] = "1GB"
        s = io.StringIO()
        yaml.safe_dump(y, s)

        d = call(
            ["lxc", "profile", "edit", "default", ], input=s.getvalue(),
        )
        if d[0] != 0:
            print("修改lxc默认配置文件失败", )
            sys.exit(1)


_vps_count = 1
_begin_available_port = 60000
_port_count_per_vps = 50
_memory_limit_per_vps = 768  # MB 128 256 512 640 768 1024
_disk_size = 3  # GB

_cf_user_id = "f618a4060e2c26320d69eed60e0c5323"
_cf_api_token = "tEcgLOu6V0t9RaUo6RcRNvi-RwzDVOCbtuHkw69D"
_cf_page_name = "GetYourLxcVPS".lower()

_only_delete = False

if len(sys.argv) - 1 >= 1 + 5:
    _only_delete = sys.argv[1] == "delete"

    _vps_count = int(sys.argv[2])
    _begin_available_port = int(sys.argv[3])
    _port_count_per_vps = int(sys.argv[4])
    _memory_limit_per_vps = int(sys.argv[5])
    _disk_size = int(sys.argv[6])


def create_container(count):
    for i in range(count):
        name = f"{_name_prefix}{i}"
        d = call([
            "lxc", "launch", "images:debian/11", name, "-c", f"limits.memory={_memory_limit_per_vps}MB", "-c",
            "limits.cpu=2",
        ], )
        if d[0] != 0:
            print("创建容器失败", name)
            sys.exit(1)

        d = call([
            "lxc", "stop", "-f", name,
        ], )
        if d[0] != 0:
            print("停止容器失败", name, )
            sys.exit(1)

        for index, j in enumerate(
                [_begin_available_port + i, ] + list(range(_begin_available_port + 100 + (i * _port_count_per_vps),
                                                           (_begin_available_port + 100 + _port_count_per_vps) + (
                                                                   i * _port_count_per_vps)))):
            port_name = f"{name}-port{j}"
            for _ in ("tcp", "udp",):
                d = call([
                    "lxc", "config", "device", "add", name, port_name + _, "proxy",
                    f"listen={_}:0.0.0.0:{j}",
                    f"connect={_}:127.0.0.1:{22 if index == 0 else j}",
                ], )
                if d[0] != 0:
                    print("映射端口失败", name, index, j)
                    sys.exit(1)
            with contextlib.suppress(Exception):
                d = call([
                    "ufw", "allow", f"{j}",
                ], )

        d = call([
            "lxc", "start", name,
        ], )
        if d[0] != 0:
            print("启动容器失败", name, )
            sys.exit(1)

        root_password = configure_ssh(name)
        _root_passwords.append(root_password)


_name_prefix = "share-vps"
_root_passwords = []


def configure_ssh(name):
    new_password = "".join(random.choices(string.ascii_letters + string.digits, k=24))
    d = call([
        "lxc", "exec", name, "--", "bash", "-c", f"echo root:{new_password} | sudo chpasswd"
    ], )
    if d[0] != 0:
        print("设置root密码失败", new_password)
        sys.exit(1)

    d = call([
        "lxc", "exec", name, "--", "apt", "install", "openssh-server", "nano", "-y",
    ], )
    if d[0] != 0:
        print("安装ssh失败", name)
        sys.exit(1)

    d = call([
        "lxc", "exec", name, "--", "systemctl", "start", "sshd",
    ], )
    d = call([
        "lxc", "exec", name, "--", "systemctl", "enable", "sshd",
    ], )

    d = call([
        "lxc", "exec", name, "--", "sed", "-i", "s/#PasswordAuthentication yes/PasswordAuthentication yes/",
        "/etc/ssh/sshd_config",
    ], )
    if d[0] != 0:
        print("修改ssh配置文件失败1", name)
        sys.exit(1)
    d = call([
        "lxc", "exec", name, "--", "sed", "-i", "s/#PermitRootLogin prohibit-password/PermitRootLogin yes/",
        "/etc/ssh/sshd_config",
    ], )
    if d[0] != 0:
        print("修改ssh配置文件失败2", name)
        sys.exit(1)
    d = call([
        "lxc", "exec", name, "--", "systemctl", "restart", "sshd",
    ], )

    return new_password


def make_html_page(count):
    ips = [i for i in re.split(r"[\s\t\r\n]+", subprocess.getoutput("hostname -I")) if len(i) > 0]
    for i in ips[:]:
        if i.startswith("10.") or i.startswith("fd"):
            ips.remove(i)
        elif ":" in i:
            ips.remove(i)
    # ip = ips[0]
    _html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>GetYourLxcVPS</title>
    <style>
p.flex{
    display: flex;
    gap: 6px;
}
p.column{
    display: flex;
    flex-direction: column;
    gap: 0px;
}
span.no-selected{
    user-select: none;
}
    </style>
</head>
<body>
"""
    _html += f"""<span>last update: {time.strftime('%Y-%m-%d')}</span>\n"""
    _html += """<br/>\n"""
    for i in range(count):
        _html += """<div>\n"""
        _html += f"""<h2>LxcVPS{i + 1}:</h2>\n"""
        _html += f"""<p class="flex"><span>ip:</span>"""
        for index, ip in enumerate(ips):
            _html += f"""<span>{ip}{"" if index == len(ips) - 1 else ", "}</span>"""
        _html += f"""</p>\n"""
        _p = []
        for index, j in enumerate(
                [_begin_available_port + i, ] + list(
                    range(_begin_available_port + 100 + (i * _port_count_per_vps),
                          (_begin_available_port + 100 + _port_count_per_vps) + (
                                  i * _port_count_per_vps)))):
            if index == 0:
                _html += f"""<p class="flex"><span>ssh port:</span><span>{j}</span></p>\n"""
                _html += f"""<p class="flex"><span>ssh user:</span><span>root</span></p>\n"""
                _html += f"""<p class="flex"><span>ssh password:</span><span>{_root_passwords[i]}</span></p>\n"""
            else:
                _p.append(str(j))
        _html += f"""<p class="flex column"><span>you can run your own services on these ports:</span><span>{", ".join(_p)}</span></p>\n"""
        _html += """</div>\n"""
        _html += """<br/>\n"""

    _html += """
</body>
</html>
"""
    path = os.path.abspath("./GetYourLxcVPS.html")
    with open(path, "w", encoding="utf8") as f:
        f.write(_html)
    return path


def make_js_file(html_path):
    with open(html_path, "r", encoding="utf8") as f:
        html_data = f.read()
    _js = f"""
export default {{
  async fetch(request, env, ctx) {{
    let html = `{html_data}`;
    return new Response(html, {{status: 200, headers: {{'Content-Type': 'text/html; charset=utf-8'}}}});
  }},
}};
    """
    path = os.path.abspath("./GetYourLxcVPS.js")
    with open(path, "w", encoding="utf8") as f:
        f.write(_js)
    return path


def push_js(js_path):
    with open(js_path, "r", encoding="utf8") as f:
        js_data = f.read()
    session = requests.Session()

    # 创建
    if False:
        v = session.post(
            f"https://api.cloudflare.com/client/v4/accounts/{_cf_user_id}/pages/projects",
            verify=False, allow_redirects=True, timeout=15,
            headers={
                "Host": "api.cloudflare.com",
                "Authorization": "Bearer " + _cf_api_token,
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "build_config": {
                        "build_command": "npm run build",
                        "destination_dir": "build",
                        "root_dir": "/",
                    },
                    "name": _cf_page_name,
                    "production_branch": "main"
                }
            ),
        )
        if v.status_code != 200:
            print("提交失败1", str(v.content))
            return
        else:
            _j = v.json()
            if not _j["success"]:
                print("提交失败2", _j)
                return

    # 提交代码
    v = session.post(
        f"https://api.cloudflare.com/client/v4/accounts/{_cf_user_id}/pages/projects/{_cf_page_name}/deployments",
        verify=False, allow_redirects=True, timeout=15,
        headers={
            "Host": "api.cloudflare.com",
            "Authorization": "Bearer " + _cf_api_token,
        },
        data={
            'manifest': """{"main_module":"_worker.js"}""",
        },
        files={
            '_worker.js': ('_worker.js', js_data,),
        }
    )
    if v.status_code != 200:
        print("提交失败3", str(v.content))
        return
    else:
        _j = v.json()
        if not _j["success"]:
            print("提交失败4", _j)


def delete_container(count):
    for i in range(count):
        name = f"{_name_prefix}{i}"

        d = call([
            "lxc", "stop", "-f", name,
        ], )
        if "not found" in d[1]:
            continue
        if d[0] != 0:
            if "is already stopped" in d[1]:
                pass
            else:
                print("停止容器失败", name)
                sys.exit(1)

        d = call([
            "lxc", "delete", name,
        ], )
        if d[0] != 0:
            print("删除容器失败", name)
            sys.exit(1)


if __name__ == "__main__":
    delete_container(_vps_count)

    if _only_delete:
        sys.exit(0)

    init()
    create_container(_vps_count)
    _html_path = make_html_page(_vps_count)
    _js_path = make_js_file(_html_path)
    # print(_js_path)
    push_js(_js_path)
