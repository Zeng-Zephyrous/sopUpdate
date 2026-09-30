import re
import string
def ExtractShipmentNo_stronger(SubjectTxt):
    _shipmentNo = []    
    # --- Remove [cid:...] patterns before processing ---
    SubjectTxt = re.sub(r'\[cid:[^\]]*\]', ' ', SubjectTxt)

    # --- FIX 1: replace non-breaking / unicode punctuation with space ---
    # This ensures things like Chinese "\uff1a" are handled
    SubjectTxt = re.sub(r'[\u3000-\u303F\uFF00-\uFFEF\uff1a\uff1b\uff0c\u3002\uff1f\uff01]', ' ', SubjectTxt)

    SubjectTxt = re.sub(r'!\[[^\]]*\]\([^\)]*\)', ' ', SubjectTxt)
    SubjectTxt = re.sub(r'(?i)<img\b[^>]*>', ' ', SubjectTxt)
    SubjectTxt = re.sub(
        r'(?i)\[(?:cid:|image:|screenshot:|https?://|www\.|/?sfc/|/?servlet\.shepherd/)[^\]]*\]',
        ' ',
        SubjectTxt,
    )
    SubjectTxt = re.sub(
        r'(?i)\b(?:https?://|www\.)[^\s\[\]<>]+',
        ' ',
        SubjectTxt,
    )

    # Remove special characters like /,._ but keep '-'
    chars = re.escape(string.punctuation.replace('-', ''))
    SubjectTxt = re.sub(r'[' + chars + ']', ' ', SubjectTxt)
    lstStrings = SubjectTxt.split()

    # --- Exclude QQ numbers: pure digits preceded by QQ/qq keyword, or @qq.com email addresses ---
    qq_numbers = set()
    # Match standalone QQ / Q Q labels without crossing a line boundary.
    qq_pattern = re.finditer(
        r'(?i)(?<![A-Za-z])q[ \t]*q(?![A-Za-z])[ \t]*[:/\\\-]?[ \t]*(\d{5,12})',
        SubjectTxt,
    )
    for m in qq_pattern:
        qq_numbers.add(m.group(1))
    # Match QQ email addresses like: 2850337389@qq.com
    qq_email_pattern = re.finditer(r'(\d{5,12})@qq\.com', SubjectTxt, re.IGNORECASE)
    for m in qq_email_pattern:
        qq_numbers.add(m.group(1))

    # --- Exclude phone numbers: patterns like +86 13119538891, +86-13119538891, 0086xxxxxxxxxx ---
    phone_numbers = set()
    # Match international phone numbers: +86 followed by 10-11 digits (with optional separators)
    phone_pattern = re.finditer(r'(?:\+\d{1,3}[\s\-]?|00\d{2,3}[\s\-]?)(\d[\d\s\-]{8,12}\d)', SubjectTxt)
    for m in phone_pattern:
        # Clean the matched number (remove spaces/dashes)
        num = re.sub(r'[\s\-]', '', m.group(1))
        phone_numbers.add(num)
        phone_numbers.add(m.group(1).strip())
    # Also match standalone mobile numbers starting with 1[3-9] (Chinese mobile, 11 digits)
    mobile_pattern = re.finditer(r'(?<![\d])(1[3-9]\d{9})(?![\d])', SubjectTxt)
    for m in mobile_pattern:
        phone_numbers.add(m.group(1))
    # Match landline-style numbers like 86 20 3597 8234 or +86 20 35978924
    landline_pattern = re.finditer(r'(?:\+\d{1,3}[\s\-]?\d{2,4}[\s\-]?)(\d{7,8})', SubjectTxt)
    for m in landline_pattern:
        phone_numbers.add(m.group(1))

    # Iterate through words in SubjectTxt
    for i, word in enumerate(lstStrings):
        if re.match(r'^(no|maeu|mr|obl)\w{9}$', word.lower()):
            if word.lower().startswith(('no', 'mr')):
                lstStrings[i] = word[2:]
            elif word.lower().startswith('maeu'):
                lstStrings[i] = word[4:]
            elif word.lower().startswith('obl'):
                lstStrings[i] = word[3:]

    numeric_list = [25,50,91,22,60,21,83,23,24,30,68,85,27,26,20,
                    11,29,59,63,65,31,41,61,82,23,60,91,63,34,20,
                    65,29,83,62,10,33,72,26,58]

    alphabetic_list = ['1K','A1','1k','04','GA','JK','VN','AP','WS','JA','HN','KH','TG','SZ','GP','AT','A3','B3','C3',
                       'D3','E3','F3','G3','H3','I3','J3','K3','L3','M3','N3','O3','P3','AA','AB','AC','Q3','R3','S3','T3',
                       'U3','V3','W3','X3','Z3','HM','VI','AF','AG','AJ','AK','AL','AM','AD','AE','AH','AI','PU','WC','CG',
                       'WM','TA','LE','PK','RG','BG','AQ','AS','AU','AV','AW','AX','AN','AR','AY','AZ','PH','VH','BO','AO',
                       'BA','BB','BC','BD','BE','BF','JC','CT','MT','KB','BS','US','RE','AD','IK','NI','NA','MK','SI','MD',
                       'UG','SS','SW','AP','IK','NP','KA']

    # --- FIX 2: strip and clean each word properly ---
    for s in lstStrings:
        _checkStr = s.strip()
        _checkStr = re.sub(r'[^\dA-Za-z]', '', _checkStr)  # remove any hidden chars
        # Skip QQ numbers
        if _checkStr in qq_numbers:
            continue
        # Skip phone numbers
        if _checkStr in phone_numbers:
            continue
        if len(_checkStr) == 9:
            if ((_checkStr.isdigit() and int(_checkStr[:2]) in numeric_list)
                and _checkStr[-4:].isdigit()):
                _shipmentNo.append(_checkStr)
            elif (_checkStr.isalnum() and not _checkStr.isalpha()
                  and _checkStr[:2] in alphabetic_list
                  and _checkStr[-4:].isdigit()):
                _shipmentNo.append(_checkStr)
            # New type bl SZHWR596K
            elif (_checkStr[:2] in alphabetic_list
                  and re.fullmatch(r'[A-Za-z]{5}\d{3}[A-Za-z]', _checkStr)):
                _shipmentNo.append(_checkStr)            

    regex_matches = re.findall(r'([A-Za-z]{2}\d{7}|[A-Za-z]{4}\d{5}|\d{9})', SubjectTxt, flags=re.IGNORECASE)
    # Filter out QQ numbers and phone numbers from regex_matches
    # regex_matches = [m for m in regex_matches if m not in qq_numbers and m not in phone_numbers]
    filtered_matches = []
    for m in regex_matches:
        if m.isdigit() and len(m) == 9:
            if any(qq.startswith(m) for qq in qq_numbers):
                continue
            if any(phone.startswith(m) for phone in phone_numbers):
                continue
        filtered_matches.append(m)
    regex_matches = filtered_matches
    if regex_matches:
        _shipmentNo.extend(regex_matches)
    if not regex_matches and len(_shipmentNo) == 0:
        return [] 
    if _shipmentNo:
        return _shipmentNo
    else:
        return ['']

emailtext="email_subject: Subject:SHANGHAI --HOCHIMINH 277493765 合并仓位 TO Yama yang \n email_body: This message was sent from outside of your organization. Please do not click links or open attachments unless you recognize the source of this email and know the content is safe.\n\nDear，\n277493765 340HQ 802342773 120GP\n\nNICOLAI MAERSK V.639S\n网页上不能更改 ，烦请帮忙合并成一票 277493765 340HQ + 120GP ，烦请更新BC，谢谢"
# def main(emailtext: str):
result = ExtractShipmentNo_stronger(emailtext)
my_list = list(set(result))
success = False
if my_list:
    success = True
# return {
#     "result": my_list,
#     "issuccess": success
# }
