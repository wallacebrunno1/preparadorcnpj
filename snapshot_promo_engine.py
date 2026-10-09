import os
import sys
import io
import json
import time
from datetime import datetime
from firebird.driver import connect

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DB_PATH = 'C:\\SDSuper\\Dados\\SDSuper.fdb'
BEFORE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snapshot_promo_before.json')

def get_connection():
    return connect(f'127.0.0.1/3050:{DB_PATH}', user='SYSDBA', password='sdkey', charset='WIN1252')

def serialize_val(val):
    if isinstance(val, (bytes, bytearray)):
        return f"<BLOB {len(val)}b>"
    elif isinstance(val, datetime):
        return val.strftime('%Y-%m-%d %H:%M:%S.%f')
    elif val is None:
        return None
    return str(val)

def take_snapshot():
    print("=" * 70)
    print("  INICIANDO SNAPSHOT COMPLETO DO BANCO (SDSuper.fdb)")
    print("=" * 70)
    start_t = time.time()
    conn = get_connection()
    cur = conn.cursor()

    # 1. Todas as tabelas de usuário
    cur.execute("""
        SELECT TRIM(RDB$RELATION_NAME) 
        FROM RDB$RELATIONS 
        WHERE (RDB$SYSTEM_FLAG = 0 OR RDB$SYSTEM_FLAG IS NULL) 
          AND RDB$VIEW_BLR IS NULL
        ORDER BY 1
    """)
    tables = [r[0] for r in cur.fetchall()]
    print(f"-> Varrendo {len(tables)} tabelas de usuário...")

    # 2. Generators
    cur.execute("""
        SELECT TRIM(RDB$GENERATOR_NAME) 
        FROM RDB$GENERATORS 
        WHERE (RDB$SYSTEM_FLAG = 0 OR RDB$SYSTEM_FLAG IS NULL)
        ORDER BY 1
    """)
    generators = [r[0] for r in cur.fetchall()]
    gen_values = {}
    for g in generators:
        try:
            cur.execute(f"SELECT GEN_ID({g}, 0) FROM RDB$DATABASE")
            gen_values[g] = cur.fetchone()[0]
        except Exception:
            pass

    snapshot = {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'generators': gen_values,
        'tables': {}
    }

    # Tabelas críticas para capturar 100% dos registros (não apenas contagem)
    deep_capture_tables = {
        'ANTPROMOCOES': 'WIDANTPROMOCAO',
        'ANTPRODUTOS': 'WIDANTPRODUTO',
        'ANTPRODUTOSPRECOS': 'WIDANTPRODUTOSPRECO',
        'PROMOCOESREGRAS': 'WIDPROMOCAOREGRA',
        'ANTCLIENTES': 'WIDCLIENTE',
        'ANTCLIGRUPOS': 'WIDCLIENTEGRUPO',
        'ANTPRODUTOSSDOFERTAS': 'WIDANTPRODUTOSSDOFERTAS',
        'ETIQUETASMODELOPROMOCAO': 'WTIPOPROMOCAO',
        'ETIQUETASPADRAOPROMOCOES': 'WIDETIQUETAPADRAO',
        'CARTOESPROMOCIONAIS': 'WIDCARTAOPROMOCIONAL',
        'PAGAMENTOSPDVPROMOCOESMEIOS': 'WIDMEIOPAGAMENTOPDV',
        'SCANNTECHPROMOCOES': 'WIDSCANNTECHPROMOCAO',
        'CONTROLE': 'WIDCONTROLE',
        'FILIAISCONTROLE': 'WIDFILIAL',
        'FILIAIS': 'WIDFILIAL'
    }

    # Também capturar o último ID da tabela LOGS
    cur.execute("SELECT MAX(WIDLOG) FROM LOGS")
    max_log_row = cur.fetchone()
    snapshot['max_log_id'] = max_log_row[0] if max_log_row else 0

    for tbl in tables:
        cur.execute(f"""
            SELECT TRIM(RDB$FIELD_NAME) 
            FROM RDB$RELATION_FIELDS 
            WHERE RDB$RELATION_NAME = '{tbl}' 
            ORDER BY RDB$FIELD_POSITION
        """)
        cols = [r[0] for r in cur.fetchall()]

        try:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            count = cur.fetchone()[0]
        except Exception:
            count = -1

        tbl_data = {
            'count': count,
            'cols': cols
        }

        # Se for tabela crítica de promoção ou pequena (<= 2000 registros), capturar registros
        if tbl in deep_capture_tables or (0 < count <= 150 and 'LOG' not in tbl and 'CUPOM' not in tbl):
            try:
                cur.execute(f"SELECT * FROM {tbl}")
                rows = cur.fetchall()
                records = []
                for r in rows:
                    rec = {c: serialize_val(val) for c, val in zip(cols, r)}
                    records.append(rec)
                tbl_data['records'] = records
            except Exception as e:
                tbl_data['records_error'] = str(e)

        snapshot['tables'][tbl] = tbl_data

    with open(BEFORE_FILE, 'w', encoding='utf-8') as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    conn.close()
    duration = time.time() - start_t
    print(f"-> Snapshot concluído com sucesso em {duration:.2f}s!")
    print(f"-> Salvo em: {BEFORE_FILE}")
    print("=" * 70)
    print("AGORA VOCÊ PODE ABRIR O SDSUPER E REALIZAR A ALTERAÇÃO NA PROMOÇÃO.")
    print("ASSIM QUE CONCLUIR, ME AVISE PARA GERAR O RELATÓRIO DE DIFERENÇAS!")
    print("=" * 70)

def compare_snapshots():
    if not os.path.exists(BEFORE_FILE):
        print(f"ERRO: Arquivo {BEFORE_FILE} não encontrado! Execute primeiro 'take'.")
        return

    with open(BEFORE_FILE, 'r', encoding='utf-8') as f:
        before = json.load(f)

    print("=" * 70)
    print("  COMPARANDO BANCO ATUAL COM O SNAPSHOT ANTERIOR")
    print("=" * 70)
    print(f"Snapshot ANTERIOR: {before['timestamp']}")
    print(f"Auditoria ATUAL:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    conn = get_connection()
    cur = conn.cursor()

    # 1. Generators
    cur.execute("""
        SELECT TRIM(RDB$GENERATOR_NAME) 
        FROM RDB$GENERATORS 
        WHERE (RDB$SYSTEM_FLAG = 0 OR RDB$SYSTEM_FLAG IS NULL)
        ORDER BY 1
    """)
    generators = [r[0] for r in cur.fetchall()]
    gen_diffs = []
    for g in generators:
        try:
            cur.execute(f"SELECT GEN_ID({g}, 0) FROM RDB$DATABASE")
            val_now = cur.fetchone()[0]
            val_before = before['generators'].get(g)
            if val_before is not None and val_now != val_before:
                gen_diffs.append((g, val_before, val_now, val_now - val_before))
        except Exception:
            pass

    if gen_diffs:
        print("\n⚡ [GENERATORS INCREMENTADOS]:")
        for g, vb, vn, d in gen_diffs:
            print(f"   * {g}: {vb} -> {vn} (+{d})")
    else:
        print("\n[-] Nenhum generator foi alterado.")

    # 2. Logs gerados
    max_log_id = before.get('max_log_id')
    if max_log_id:
        try:
            cur.execute(f"""
                SELECT WIDLOG, WIDFILIAL, WIDUSUARIO, WDATALOG, WROTINA, WHISTORICO, WTABELA, WIDREGISTRO
                FROM LOGS
                WHERE WIDLOG > {max_log_id}
                ORDER BY WIDLOG ASC
            """)
            logs = cur.fetchall()
            if logs:
                print(f"\n📋 [LOGS DE AUDITORIA GERADOS PELO SDSUPER ({len(logs)})]:")
                for l in logs:
                    hist = l[5]
                    if isinstance(hist, (bytes, bytearray)):
                        hist = hist.decode('latin1', errors='ignore')
                    print(f"   * Log #{l[0]} | Filial {l[1]} | Usuário {l[2]} | Rotina: '{l[4]}' | Tabela: {l[6]} (Reg: {l[7]})")
                    if hist:
                        for line in str(hist).strip().split('\n'):
                            print(f"     > {line}")
            else:
                print("\n[-] Nenhum novo registro na tabela LOGS.")
        except Exception as e:
            print(f"Aviso ao consultar LOGS: {e}")

    # 3. Diferenças em tabelas
    print("\n🔍 [ALTERAÇÕES NAS TABELAS DO BANCO]:")
    total_modifications = 0

    for tbl, before_info in before['tables'].items():
        cols = before_info['cols']
        count_before = before_info['count']

        try:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            count_now = cur.fetchone()[0]
        except Exception:
            count_now = -1

        # Mudança na contagem de registros
        if count_now != count_before:
            delta = count_now - count_before
            print(f"\n📦 TABELA: {tbl} (Contagem alterada: {count_before} -> {count_now} | Delta: {delta:+d})")
            total_modifications += 1

        # Verificação profunda de registros gravados
        if 'records' in before_info:
            try:
                cur.execute(f"SELECT * FROM {tbl}")
                rows_now = cur.fetchall()
                recs_now = [{c: serialize_val(val) for c, val in zip(cols, r)} for r in rows_now]

                before_records = before_info['records']

                # Identificar chave primária / identificador
                pk_candidates = [c for c in cols if c.startswith('WID') or c.startswith('ID')]
                pk = pk_candidates[0] if pk_candidates else cols[0]

                before_map = {r.get(pk): r for r in before_records if pk in r}
                now_map = {r.get(pk): r for r in recs_now if pk in r}

                # Inseridos
                inserted = [now_map[k] for k in now_map if k not in before_map]
                # Excluídos
                deleted = [before_map[k] for k in before_map if k not in now_map]
                # Alterados
                updated = []
                for k in now_map:
                    if k in before_map:
                        r_before = before_map[k]
                        r_now = now_map[k]
                        diffs = {}
                        for c in cols:
                            if r_before.get(c) != r_now.get(c):
                                diffs[c] = {'antes': r_before.get(c), 'depois': r_now.get(c)}
                        if diffs:
                            updated.append({'pk': k, 'diffs': diffs})

                if inserted or deleted or updated:
                    if count_now == count_before:
                        print(f"\n📦 TABELA: {tbl} (Registros modificados)")
                        total_modifications += 1

                    if inserted:
                        print(f"   [+] INSERIDOS ({len(inserted)}):")
                        for ins in inserted:
                            print(f"       * {pk}={ins.get(pk)}: {ins}")

                    if deleted:
                        print(f"   [-] REMOVIDOS ({len(deleted)}):")
                        for rem in deleted:
                            print(f"       * {pk}={rem.get(pk)}: {rem}")

                    if updated:
                        print(f"   [*] ALTERADOS ({len(updated)}):")
                        for up in updated:
                            print(f"       * {pk}={up['pk']}:")
                            for col_name, chg in up['diffs'].items():
                                print(f"         - {col_name}: '{chg['antes']}' -> '{chg['depois']}'")

            except Exception as e:
                print(f"Erro ao analisar diff detalhado de {tbl}: {e}")

    if total_modifications == 0:
        print("[-] Nenhuma alteração detectada no banco até o momento.")
    else:
        print(f"\n=> Total de tabelas com modificações: {total_modifications}")

    print("=" * 70)
    conn.close()

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'take'
    if cmd == 'take':
        take_snapshot()
    elif cmd == 'diff':
        compare_snapshots()
    else:
        print("Uso: python snapshot_promo_engine.py [take|diff]")
