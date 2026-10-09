def examine_binary(db_path):
    with open(db_path, "rb") as f:
        data = f.read()
    
    idx = 0
    while True:
        idx = data.find(b'P02322', idx)
        if idx == -1:
            break
        start = max(0, idx - 20)
        end = min(len(data), idx + 20)
        print(f"Found P02322 at offset {idx}")
        chunk = data[start:end]
        hex_str = ' '.join(f'{b:02x}' for b in chunk)
        print("Hex:", hex_str)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print("Ascii:", ascii_str)
        idx += 1

if __name__ == "__main__":
    examine_binary("data/faces_db_recovery.db")
