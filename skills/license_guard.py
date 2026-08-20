# -*- coding: utf-8 -*-
"""skills.license_guard —— wave漫流 激活码验证（内置公钥，RSA 验签 + 机器码绑定 + 3次错误锁定）

安全模型：
- 激活码 = RSA-SHA256 签名（作者私钥生成，程序内置公钥验证）→ 别人无法伪造
- 激活码内容 = 机器码|到期时间戳（签名+payload 整体 Base58）→ 不可猜、无规律
- 机器码绑定：激活码只对生成时的机器有效（防一码多用）
- 3 次错误 → 锁定（必须输入正确激活码才能解锁）；锁定状态存本地

激活流程：
  偏好设置 → 显示机器码 → 作者用私钥生成激活码 → 买家粘贴 → 验证通过
"""
import os, json, time, base64, hashlib, hmac as _hmac, uuid


def _d(blob):
    """XOR 解码（混淆辅助）：hex 字节串 → 字节 → XOR 还原。"""
    return bytes(x ^ 0x5A for x in bytes.fromhex(blob.decode("ascii")))

# ── 内置公钥（由 gen_license.py 生成 public_key.pem 后替换此处）──
# 部署时用 gen_license.py 首次运行生成的 public_key.pem 内容替换下面字符串
# 公钥已混淆（XOR 90 编码，运行时解码）
PUBLIC_KEY_PEM = _d(b'7777777777181f1d13147a0a0f181613197a111f037777777777501713131813301b14183d312b3231331d632d6a181b0b1f1c1b1b15191b0b621b17131318193d11191b0b1f1b2f2a3e236a160c0a1715323e19681d3e683e353e503e2d31333f2a620d3d6c182f1b0063366d156b1e3d36166a6e112f10203e152b232b1e083213182e0f14396c390e2e0a37362e1d7519330c6c316f1c00140e7150752320181f3929292f3f0c136a3c186f323537223d11631f2d2b1c6e353b6d2b3f231d0b391e33342a683b0f1f3e6f0f75376c3f030e32141f0e380075300330502002131730376b3d6b393310136d350b6a7517632f0a1723712a6c0a00280d193d1e31287171120d1363372971141b1e33190e390b1f0e136d3b6b030303632e503d1408232d6a6c1d19342d1909106d33096c6d1508626e3d3c163c3715376f3b0210342e0a023f0f3d160869690e681910121e1c372071116a620d356f6a3d6e500d6822313618090b180d361c716d196d191c191e37170e3375282220202c02313139626e0b636a63312317091e38093d140c186c1108176e396e2d13180a341d502b2d131e1b0b1b185077777777771f141e7a0a0f181613197a111f03777777777750')

LICENSE_FILE = "license.json"   # 激活状态 + 错误计数存储
LOCKOUT_AFTER = 3               # 错误 3 次锁定

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _b58decode(s):
    s = s.replace("-", "").strip()
    n = 0
    for c in s:
        n = n * 58 + BASE58_ALPHABET.index(c)
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    pad = 0
    for c in s:
        if c == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + b


def _b58encode(b):
    n = int.from_bytes(b, "big")
    s = ""
    while n > 0:
        n, r = divmod(n, 58)
        s = BASE58_ALPHABET[r] + s
    for byte in b:
        if byte == 0:
            s = "1" + s
        else:
            break
    return s


def get_machine_code():
    """本机唯一机器码：CPU+主板+网卡 MAC 哈希。"""
    parts = []
    try:
        parts.append(platform_node())
    except Exception:
        pass
    try:
        parts.append(uuid.getnode().__str__())
    except Exception:
        pass
    try:
        parts.append(win_cpu_id())
    except Exception:
        pass
    raw = "|".join(parts)
    h = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest().upper()
    # 分成 4 组 8 位，便于阅读
    return "-".join(h[i:i+8] for i in range(0, 32, 8))


def platform_node():
    import socket
    return socket.gethostname()


def win_cpu_id():
    try:
        import subprocess
        r = subprocess.run(["wmic", "cpu", "get", "ProcessorId"],
                           capture_output=True, text=True, timeout=10)
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            if line and line.lower() != "processorid":
                return line
    except Exception:
        pass
    return ""


def _load_state():
    try:
        if os.path.exists(LICENSE_FILE):
            with open(LICENSE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"activated": False, "errors": 0, "machine": "", "expire": 0, "code": ""}


def _save_state(state):
    try:
        with open(LICENSE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def is_activated():
    """检查是否已激活（且未过期、机器码匹配）。"""
    try:
        st = _load_state()
        if not st.get("activated"):
            return False
        if st.get("machine") != get_machine_code():
            return False
        if st.get("expire", 0) and time.time() > st["expire"]:
            return False
        return True
    except Exception:
        return False


def remaining_errors():
    """剩余错误机会（锁定后为 0）。"""
    try:
        st = _load_state()
        return max(0, LOCKOUT_AFTER - st.get("errors", 0))
    except Exception:
        return LOCKOUT_AFTER


def verify_license(code):
    """验证激活码。返回 (ok, msg)。

    - 验签失败 → 错误计数+1（3 次锁定）
    - 机器码不匹配 → 错误计数+1
    - 已过期 → 不计数（提示续期）
    - 验证通过 → 记录激活状态（清除错误计数）
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.backends import default_backend
        HAS_CRYPTO = True
    except Exception:
        HAS_CRYPTO = False

    st = _load_state()
    # 先验证激活码（锁定状态也允许验证：输对即解锁）
    if not code or not code.strip():
        return False, "请输入激活码"

    # 2026-08-10：兼容 V2（授权码激活码）。先试旧格式，失败再试 V2。
    if not HAS_CRYPTO:
        ok, msg = _verify_rsa_pure(code.strip())
    else:
        ok, msg = _verify_rsa_crypto(code.strip())
    if not ok:
        ok2, msg2 = _verify_v2(code.strip())
        if ok2:
            ok, msg = True, msg2
        elif msg2 != "not_v2":
            # V2 识别到了但验证失败（配额/篡改/白名单/超期等）——用 V2 的精确原因
            msg = msg2

    if ok:
        # 验证通过：记录激活（清除错误计数，解除锁定）
        st["activated"] = True
        st["errors"] = 0
        st["machine"] = get_machine_code()
        st["expire"] = msg["expire"]
        st["card_type"] = msg.get("card_type", "")
        st["code"] = code.strip()
        _save_state(st)
        # 永久卡显示"永久有效"，否则显示到期日期
        if msg["expire"] >= 253402300000:
            return True, "激活成功，永久有效"
        return True, "激活成功，有效期至 %s" % time.strftime("%Y-%m-%d", time.localtime(msg["expire"]))

    # 锁定状态下的错误输入：直接报锁定
    if st.get("errors", 0) >= LOCKOUT_AFTER and not st.get("activated"):
        return False, "已锁定（错误次数过多）。请输入正确的激活码解锁。"

    # 失败计数（过期/吊销类不计数：expired=激活码过期 / voucher_expired=授权码过期 / revoked=授权码被吊销）
    if msg not in ("expired", "voucher_expired", "revoked"):
        st["errors"] = st.get("errors", 0) + 1
        _save_state(st)
        left = LOCKOUT_AFTER - st["errors"]
        if left <= 0:
            return False, "激活码错误次数过多，程序已锁定！"
        if msg == "revoked":
            return False, "该授权码已被作者吊销，请联系卖家。"
        if msg == "voucher_expired":
            return False, "授权码已过期，请联系卖家续期。"
        return False, "激活码无效（剩余机会 %d 次）" % left
    if msg == "revoked":
        return False, "该授权码已被作者吊销，请联系卖家。"
    if msg == "voucher_expired":
        return False, "授权码已过期，请联系卖家续期。"
    return False, "激活码已过期"


def _verify_rsa_crypto(code):
    """用 cryptography 库验签。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.backends import default_backend
    try:
        blob = _b58decode(code)
        if len(blob) < 256 + 5:
            return False, "invalid"
        sig, payload = blob[:256], blob[256:]
        pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM, backend=default_backend())
        pub.verify(sig, payload, padding.PKCS1v15(), hashes.SHA256())
        # 解析 payload：machine|expire（老格式） 或 machine|card_type|expire（新格式，含卡类型）
        text = payload.decode("utf-8", "ignore")
        parts = text.split("|")
        if len(parts) >= 3:
            machine, card_type, expire_s = parts[0], parts[1], parts[2]
            expire = int(expire_s)
        elif len(parts) == 2:
            machine, expire_s = parts
            card_type = ""
            expire = int(expire_s)
        else:
            return False, "invalid"
        if machine.strip().upper() != get_machine_code():
            return False, "machine"
        if time.time() > expire:
            return False, "expired"
        return True, {"expire": expire, "card_type": card_type}
    except Exception:
        return False, "invalid"


def _rsa_pkcs1_verify(sig, payload, pem=None):
    """纯 Python RSA-SHA256 PKCS1v15 验签（不依赖 cryptography）。
    2026-08-11 修复：exe 打包时 cryptography Python 模块缺失导致 V2 激活码
    'voucher_invalid'——授权码验签改用纯 Python 兜底，任何环境都能验签。"""
    try:
        pem = pem or PUBLIC_KEY_PEM
        b64 = b"".join(l.strip() for l in pem.splitlines()
                       if l.strip() and b"-----" not in l)
        der = base64.b64decode(b64)
        n, e = _parse_spki(der)
        sig_int = int.from_bytes(sig, "big")
        dec = pow(sig_int, e, n).to_bytes(256, "big")
        digest = hashlib.sha256(payload).digest()
        dig_info = b"\x30\x31\x30\x0d\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01\x05\x00\x04\x20" + digest
        if not dec.startswith(b"\x00\x01"):
            return False
        sep = dec.find(b"\x00", 2)
        if sep < 0 or dec[sep+1:] != dig_info:
            return False
        return True
    except Exception:
        return False


def _verify_rsa_pure(code):
    """纯 Python RSA 验签（无 cryptography 库时的兜底）。"""
    try:
        blob = _b58decode(code)
        if len(blob) < 256 + 5:
            return False, "invalid"
        sig, payload = blob[:256], blob[256:]
        if not _rsa_pkcs1_verify(sig, payload):
            return False, "invalid"
        text = payload.decode("utf-8", "ignore")
        parts = text.split("|")
        if len(parts) >= 3:
            machine, card_type, expire_s = parts[0], parts[1], parts[2]
            expire = int(expire_s)
        elif len(parts) == 2:
            machine, expire_s = parts
            card_type = ""
            expire = int(expire_s)
        else:
            return False, "invalid"
        if machine.strip().upper() != get_machine_code():
            return False, "machine"
        if time.time() > expire:
            return False, "expired"
        return True, {"expire": expire, "card_type": card_type}
    except Exception:
        return False, "invalid"


def _verify_v2(code):
    """验证激活码 V2（授权码 + 派生段）。返回 (True, msg_dict) 或 (False, 原因)。

    V2 格式（2026-08-10 授权码机制）：
      激活码 = 授权码 + '|' + Base58(序号|机器码|卡类型|到期|HMAC16hex)
      授权码 = WV + Base58(RSA签名(WV|授权码ID|配额N|授权码有效期|卡类型白名单|HMAC密钥))
    验证链：授权码 RSA 验签 → 授权码未过期 → 派生段 HMAC 防篡改 → 序号∈[1,N]
           → 卡类型∈白名单 → 到期≤授权码有效期 → 机器码匹配 → 未过期
    """
    try:
        if "|" not in code:
            return False, "not_v2"
        v_b58, d_b58 = code.split("|", 1)
        v_b58 = v_b58.strip().replace("-", "")
        if not v_b58.startswith("WV"):
            return False, "not_v2"
        blob = _b58decode(v_b58[2:])
        if len(blob) < 256 + 5:
            return False, "voucher_invalid"
        sig, payload = blob[:256], blob[256:]
        # RSA 验签：优先 cryptography，缺失/失败时纯 Python 兜底（2026-08-11 修复）
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            from cryptography.hazmat.backends import default_backend
            pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM, backend=default_backend())
            pub.verify(sig, payload, padding.PKCS1v15(), hashes.SHA256())
        except Exception:
            if not _rsa_pkcs1_verify(sig, payload):
                return False, "voucher_invalid"
        parts = payload.decode("utf-8", "ignore").split("|")
        if len(parts) != 6 or parts[0] != "WV":
            return False, "voucher_invalid"
        vid, quota, vexp, types_s, key_hex = parts[1], int(parts[2]), int(parts[3]), parts[4], parts[5]
        if vexp < 253402300799 and time.time() > vexp:
            return False, "voucher_expired"
        # 派生段
        try:
            dv = _b58decode(d_b58).decode("utf-8", "ignore")
            seq_s, machine, card_type, expire_s, h_hex = dv.split("|")
            seq, expire = int(seq_s), int(expire_s)
        except Exception:
            return False, "derived_invalid"
        key_bytes = bytes.fromhex(key_hex)
        derived = "%d|%s|%s|%d" % (seq, machine, card_type, expire)
        expect = _hmac.new(key_bytes, derived.encode("utf-8"), hashlib.sha256).digest()[:16].hex()
        if expect.lower() != h_hex.strip().lower():
            return False, "tampered"
        if not (1 <= seq <= quota):
            return False, "seq_out_of_quota"
        types_list = [t for t in types_s.split(",") if t]
        if card_type not in types_list:
            return False, "card_type_not_allowed"
        if expire > vexp:
            return False, "expire_over_voucher"
        if machine.strip().upper() != get_machine_code():
            return False, "machine"
        # 2026-08-10 吊销黑名单：wave漫流.exe 同目录 revoke_list.json 内列出的授权码ID → 拒绝激活
        # （作者发现授权码被滥用后，生成 revoke_list.json 发给下级/买家放运行目录即可吊销）
        try:
            _rl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "revoke_list.json")
            if not os.path.exists(_rl_path):
                _rl_path = os.path.join(os.getcwd(), "revoke_list.json")
            if os.path.exists(_rl_path):
                with open(_rl_path, "r", encoding="utf-8") as _f:
                    _rl = json.load(_f)
                _revoked = set(str(x).strip().upper() for x in (_rl.get("revoked") or []))
                if vid.strip().upper() in _revoked:
                    return False, "revoked"
        except Exception:
            pass
        if time.time() > expire:
            return False, "expired"
        return True, {"expire": expire, "card_type": card_type, "vid": vid, "seq": seq}
    except Exception:
        return False, "invalid"


def _parse_spki(der):
    """解析 SubjectPublicKeyInfo（RSA）：返回 (n, e)。

    完整 ASN.1 TLV 解析：
    SEQUENCE { SEQUENCE { OID rsaEncryption, NULL }, BIT STRING { SEQUENCE { INTEGER n, INTEGER e } } }
    """
    try:
        off = 0
        def read_tlv(d, o):
            """返回 (tag, value_bytes, next_off)。支持长格式长度。"""
            tag = d[o]; o += 1
            ln = d[o]; o += 1
            if ln & 0x80:
                cnt = ln & 0x7f
                ln = int.from_bytes(d[o:o+cnt], 'big'); o += cnt
            return tag, d[o:o+ln], o + ln
        # 外层 SEQUENCE
        tag, inner, off = read_tlv(der, 0)
        if tag != 0x30:
            raise ValueError('not SEQUENCE')
        # 内层: algorithm SEQUENCE
        tag, alg, p = read_tlv(inner, 0)
        # BIT STRING
        tag, bitstr, p = read_tlv(inner, p)
        if tag != 0x03:
            raise ValueError('not BIT STRING')
        if bitstr[0] != 0:  # 未用位
            raise ValueError('BIT STRING unused bits')
        # RSAPublicKey SEQUENCE
        tag, rsa, p = read_tlv(bitstr, 1)
        if tag != 0x30:
            raise ValueError('not RSA SEQ')
        # INTEGER n
        tag, n_bytes, p = read_tlv(rsa, 0)
        n = int.from_bytes(n_bytes, 'big')
        # INTEGER e
        tag, e_bytes, p = read_tlv(rsa, p)
        e = int.from_bytes(e_bytes, 'big')
        return n, e
    except Exception:
        raise ValueError('bad SPKI')


def reset_license():
    """重置激活状态（作者调试用/买家重装）。"""
    try:
        if os.path.exists(LICENSE_FILE):
            os.remove(LICENSE_FILE)
    except Exception:
        pass
