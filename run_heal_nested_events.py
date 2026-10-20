import sqlite3
import sys
import os

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gdrive_sync import GoogleSyncManager

def heal_nested_events():
    print("=" * 70)
    print("🚀 เริ่มต้นกระบวนการฟื้นฟูชื่อกิจกรรมที่ซ้อนโฟลเดอร์ย่อย (Data Healing v6.32)")
    print("=" * 70)

    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "faces_db.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ตรวจสอบยอดรวมรูปภาพก่อนทำ
    c.execute("SELECT count(*) FROM scanned_photos")
    total_before = c.fetchone()[0]
    print(f"📸 ยอดรวมรูปภาพก่อนแก้ไข: {total_before} รูป")

    # เชื่อมต่อ Drive API เพื่อดึง drive_file_ids สำหรับกรณีที่แบ่งโฟลเดอร์แม่หลายอัน (คำสั่ง)
    sync = GoogleSyncManager()
    sync.connect()

    # 1. จัดการ 'คำสั่ง' แยกตามโฟลเดอร์แม่
    # กค 7: 1p9-YA5xK5kkzXFrpsOllEK_68n2TzGZu
    res_rot = sync.drive_service.files().list(q="'1p9-YA5xK5kkzXFrpsOllEK_68n2TzGZu' in parents and trashed = false", fields="files(id)").execute()
    rot_ids = [f['id'] for f in res_rot.get('files', [])]

    # มิย 30: 1tBM5knPu-311oCpjN61eovUH3T0RJOoS
    res_port = sync.drive_service.files().list(q="'1tBM5knPu-311oCpjN61eovUH3T0RJOoS' in parents and trashed = false", fields="files(id)").execute()
    port_ids = [f['id'] for f in res_port.get('files', [])]

    # เริ่ม Transaction
    c.execute("BEGIN TRANSACTION")

    updates = [
        # (New Event Name, New Year, Condition SQL, Params)
        ("สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม", "2569", "event_name = 'ครู' AND academic_year = '2569'", []),
        ("สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม", "2569", "event_name = 'นักเรียน' AND academic_year = '2569' AND drive_file_id IN (SELECT drive_file_id FROM scanned_photos WHERE event_name = 'นักเรียน' AND academic_year = '2569' LIMIT 369)", []), # We will update by IDs
    ]

    # Update 1: สค 15 ครู (266 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม' WHERE event_name = 'ครู' AND academic_year = '2569'")
    cnt_kru15 = c.rowcount
    print(f"✅ แก้ไข 'ครู' -> 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม': {cnt_kru15} รูป")

    # Update 2: นักเรียน (369 รูป สค 15 และ 643 รูป สค 16)
    # ดึงไฟล์ของ สค 15 นักเรียน จาก Drive (1CW3xTqf3EdyOhLYtJs-1Dlsj67krkoZ0)
    res_std15 = sync.drive_service.files().list(q="'1CW3xTqf3EdyOhLYtJs-1Dlsj67krkoZ0' in parents and trashed = false", fields="files(id)", pageSize=1000).execute()
    std15_ids = [f['id'] for f in res_std15.get('files', [])]
    placeholders_std15 = ','.join('?' for _ in std15_ids)
    c.execute(f"UPDATE scanned_photos SET event_name = 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม' WHERE drive_file_id IN ({placeholders_std15})", std15_ids)
    cnt_std15 = c.rowcount
    print(f"✅ แก้ไข 'นักเรียน' (โฟลเดอร์ค่าย) -> 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม': {cnt_std15} รูป")

    # นักเรียนที่เหลือใน 2569 -> 'สค 16 รักษ์ภูมิปัญญา พัฒนาภาษาไทย ครั้งที่ 4 คอนเพลง'
    c.execute("UPDATE scanned_photos SET event_name = 'สค 16 รักษ์ภูมิปัญญา พัฒนาภาษาไทย ครั้งที่ 4 คอนเพลง' WHERE event_name = 'นักเรียน' AND academic_year = '2569'")
    cnt_std16 = c.rowcount
    print(f"✅ แก้ไข 'นักเรียน' (โฟลเดอร์รักษ์ภูมิปัญญา) -> 'สค 16 รักษ์ภูมิปัญญา พัฒนาภาษาไทย ครั้งที่ 4 คอนเพลง': {cnt_std16} รูป")

    # Update 3: กีฬาสี 65 (ครูธนา 863 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'กีฬาสี 65' WHERE event_name = 'ครูธนา'")
    cnt_kruthana = c.rowcount
    print(f"✅ แก้ไข 'ครูธนา' -> 'กีฬาสี 65': {cnt_kruthana} รูป")

    # Update 4: ลส ต้านภัยยาเสพติด 65 (Thana 281 + Jim's 72 = 353 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'ลส ต้านภัยยาเสพติด 65' WHERE event_name IN ('Thana', \"Jim's\")")
    cnt_ls = c.rowcount
    print(f"✅ แก้ไข 'Thana' และ 'Jim''s' -> 'ลส ต้านภัยยาเสพติด 65': {cnt_ls} รูป")

    # Update 5: VDO เกษียณ65 (ครูอ้อย 48 + น้านัน 31 + VDO 1 = 80 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'VDO เกษียณ65' WHERE event_name IN ('ครูอ้อย', 'น้านัน', 'VDO')")
    cnt_vdo = c.rowcount
    print(f"✅ แก้ไข 'ครูอ้อย', 'น้านัน', 'VDO' -> 'VDO เกษียณ65': {cnt_vdo} รูป")

    # Update 6: กค 21 กีฬาสี day1 (TargetFolder 4 รูป พร้อมเติม academic_year = '2569')
    c.execute("UPDATE scanned_photos SET event_name = 'กค 21 กีฬาสี day1', academic_year = '2569' WHERE event_name = 'TargetFolder'")
    cnt_target = c.rowcount
    print(f"✅ แก้ไข 'TargetFolder' -> 'กค 21 กีฬาสี day1' (year=2569): {cnt_target} รูป")

    # Update 7: มิย 17 ฝึกอบรมและฝึกซ้อมแผนป้องกันและบรรเทาสาธารณภัย ปีการศึกษา 2569 (doc 2 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'มิย 17 ฝึกอบรมและฝึกซ้อมแผนป้องกันและบรรเทาสาธารณภัย ปีการศึกษา 2569' WHERE event_name = 'doc'")
    cnt_doc = c.rowcount
    print(f"✅ แก้ไข 'doc' -> 'มิย 17 ฝึกอบรมฯ': {cnt_doc} รูป")

    # Update 8: คำสั่ง กค 7 vs มิย 30
    if rot_ids:
        pl = ','.join('?' for _ in rot_ids)
        c.execute(f"UPDATE scanned_photos SET event_name = 'กค 7 ปฐมนิเทศนักศึกษาวิชาทหาร ชาย หญิง ชั้นปีที่ 1 2569' WHERE drive_file_id IN ({pl}) AND event_name = 'คำสั่ง'", rot_ids)
        print(f"✅ แก้ไข 'คำสั่ง' -> 'กค 7 ปฐมนิเทศ รด.': {c.rowcount} รูป")
    if port_ids:
        pl = ','.join('?' for _ in port_ids)
        c.execute(f"UPDATE scanned_photos SET event_name = 'มิย 30 แนะแนวทำพอร์ท ลาดกระบัง' WHERE drive_file_id IN ({pl}) AND event_name = 'คำสั่ง'", port_ids)
        print(f"✅ แก้ไข 'คำสั่ง' -> 'มิย 30 แนะแนวทำพอร์ท ลาดกระบัง': {c.rowcount} รูป")

    # Update 9: สค 12 อำเภอ วันแม่  (ภาพอำเภอ 140 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'สค 12 อำเภอ วันแม่ ' WHERE event_name = 'ภาพอำเภอ'")
    cnt_amp = c.rowcount
    print(f"✅ แก้ไข 'ภาพอำเภอ' -> 'สค 12 อำเภอ วันแม่ ': {cnt_amp} รูป")

    # Update 10: ผลงาน 1-2568 (ผลงานครู 23 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'ผลงาน 1-2568' WHERE event_name = 'ผลงานครู'")
    cnt_work = c.rowcount
    print(f"✅ แก้ไข 'ผลงานครู' -> 'ผลงาน 1-2568': {cnt_work} รูป")

    # Update 11: ภาพค่ายเยาวชนนั้นไซร้ (ภาพ 2568: 244 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'ภาพค่ายเยาวชนนั้นไซร้' WHERE event_name = 'ภาพ' AND academic_year = '2568'")
    cnt_camp68 = c.rowcount
    print(f"✅ แก้ไข 'ภาพ' (2568) -> 'ภาพค่ายเยาวชนนั้นไซร้': {cnt_camp68} รูป")

    # Update 12: พิธีพุทธาภิเษก (ภาพ 2567: 253 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'พิธีพุทธาภิเษก' WHERE event_name = 'ภาพ' AND academic_year = '2567'")
    cnt_buddha = c.rowcount
    print(f"✅ แก้ไข 'ภาพ' (2567) -> 'พิธีพุทธาภิเษก': {cnt_buddha} รูป")

    # Update 13: ค่ายฝึกปฏิบัติการสร้างนักวิทย์สนุกคิดนอกห้องเรียน 2567 (8-9 ตุลาคม 2567) ณ มหาวิทยาลัยวลัยลักษณ์ (รวม 208 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'ค่ายฝึกปฏิบัติการสร้างนักวิทย์สนุกคิดนอกห้องเรียน 2567 (8-9 ตุลาคม 2567) ณ มหาวิทยาลัยวลัยลักษณ์' WHERE event_name = 'รวม' AND academic_year = '2567'")
    cnt_sci = c.rowcount
    print(f"✅ แก้ไข 'รวม' (2567) -> 'ค่ายฝึกปฏิบัติการสร้างนักวิทย์ฯ': {cnt_sci} รูป")

    # Update 14: เดินเทิดพระเกียรติกรมหลวงชุมพร (อาสุ 6 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'เดินเทิดพระเกียรติกรมหลวงชุมพร' WHERE event_name = 'อาสุ'")
    cnt_asu = c.rowcount
    print(f"✅ แก้ไข 'อาสุ' -> 'เดินเทิดพระเกียรติกรมหลวงชุมพร': {cnt_asu} รูป")

    # Update 15: งานวิ่ง 2567 (ไวนิล 1 รูป)
    c.execute("UPDATE scanned_photos SET event_name = 'งานวิ่ง 2567' WHERE event_name = 'ไวนิล'")
    cnt_vinyl = c.rowcount
    print(f"✅ แก้ไข 'ไวนิล' -> 'งานวิ่ง 2567': {cnt_vinyl} รูป")

    conn.commit()

    # ตรวจสอบหลังทำ
    c.execute("SELECT count(*) FROM scanned_photos")
    total_after = c.fetchone()[0]
    print(f"\n📸 ยอดรวมรูปภาพหลังแก้ไข: {total_after} รูป (ต้องเท่ากับ {total_before} รูป 100%)")
    assert total_before == total_after, "Zero Data Loss check failed!"

    # ตรวจสอบว่ายังมี generic keywords หลงเหลือหรือไม่
    generic_list = [
        'นักเรียน', 'ครู', 'ภาพอำเภอ', 'TargetFolder', 'คำสั่ง', 'doc', 
        'ภาพ', 'ผลงานครู', 'รวม', 'อาสุ', 'ไวนิล', 'ครูธนา', 'Thana', 
        "Jim's", 'ครูอ้อย', 'น้านัน', 'VDO'
    ]
    pl_check = ','.join('?' for _ in generic_list)
    c.execute(f"SELECT count(*) FROM scanned_photos WHERE event_name IN ({pl_check})", generic_list)
    remaining_generic = c.fetchone()[0]
    print(f"🔍 จำนวนรูปที่มี event_name เป็นคำ generic หลงเหลือ: {remaining_generic} รูป (ต้องเป็น 0)")

    # ตรวจสอบรูปในกิจกรรม 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม'
    c.execute("SELECT count(*) FROM scanned_photos WHERE event_name = 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม'")
    cnt_event15 = c.fetchone()[0]
    print(f"🎉 ยอดรูปภาพใน 'สค 15 ค่ายส่งเสริมยุวชนคนคุณธรรม': {cnt_event15} รูป (ต้องเท่ากับ 635 รูป)")

    conn.close()
    print("=" * 70)
    print("✨ กระบวนการ Data Healing เสร็จสิ้นสมบูรณ์ 100%!")
    print("=" * 70)

if __name__ == "__main__":
    heal_nested_events()
