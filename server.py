import http.server
import socketserver
import json
import urllib.parse
import urllib.request
import os
import sys
import webbrowser
import unicodedata
import socket
import re
import hashlib
import secrets
import time
import threading
import base64
from datetime import datetime
import requests
from firebird.driver import connect

try:
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography import x509
    HAS_CRYPTOGRAPHY = True
except ImportError:
    HAS_CRYPTOGRAPHY = False

PORT = int(os.environ.get("PORT", 8089))

class FirebirdManager:
    @staticmethod
    def detect_registry():
        try:
            import winreg
            paths = [
                r'SOFTWARE\WOW6432Node\SDInformatica\SDSuper',
                r'SOFTWARE\SDInformatica\SDSuper'
            ]
            for path in paths:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as k:
                        def get_v(name, default=None):
                            try:
                                v, _ = winreg.QueryValueEx(k, name)
                                return v
                            except:
                                return default
                        
                        bd_ip = get_v('BDIPServidor')
                        banco_linux = get_v('BancoLinux', 'N')
                        porta = get_v('portaBanco', 3050)
                        letra = get_v('LetraBanco', 'C')
                        cnpj = get_v('cnpjLoja', '')
                        
                        if bd_ip:
                            ip_str = str(bd_ip).strip()
                            is_linux = (str(banco_linux).strip().upper() == 'S')
                            
                            if ip_str.upper() == 'LOCALHOST':
                                ip_display = '127.0.0.1'
                                is_localhost = True
                            else:
                                ip_display = ip_str
                                is_localhost = (ip_str == '127.0.0.1')
                            
                            if is_linux:
                                db_path = "/SDSuper/Dados/SDSuper.fdb"
                                tipo_label = "Servidor VM (Linux)"
                            else:
                                drive = letra if letra else 'C'
                                db_path = f"{drive}:\\SDSuper\\Dados\\SDSuper.fdb"
                                tipo_label = "Banco no Windows"
                                
                            return {
                                "found": True,
                                "ip": ip_display,
                                "raw_ip": ip_str,
                                "port": int(porta) if str(porta).isdigit() else 3050,
                                "is_linux": is_linux,
                                "is_localhost": is_localhost,
                                "db_path": db_path,
                                "tipo_label": tipo_label,
                                "cnpj": cnpj
                            }
                except Exception:
                    continue
        except Exception as e:
            return {"found": False, "error": str(e)}
        return {"found": False}

    @staticmethod
    def get_filial_precos_registry():
        try:
            import winreg
            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\SDInformatica\SDSuper'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\SDInformatica\SDSuper'),
                (winreg.HKEY_CURRENT_USER, r'Software\SDInformatica\SDSuper')
            ]
            for root, p in keys:
                try:
                    with winreg.OpenKey(root, p) as k:
                        val, _ = winreg.QueryValueEx(k, 'FilialPrecosPromocao')
                        if val is not None:
                            return int(val)
                except Exception:
                    pass
        except Exception:
            pass
        return None

    @staticmethod
    def set_filial_precos_registry(filial_id):
        updated = False
        try:
            import winreg
            filial_int = int(filial_id)
            keys = [
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\SDInformatica\SDSuper'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\SDInformatica\SDSuper'),
                (winreg.HKEY_CURRENT_USER, r'Software\SDInformatica\SDSuper')
            ]
            for root, p in keys:
                for flag in [winreg.KEY_SET_VALUE | getattr(winreg, 'KEY_WOW64_32KEY', 0), winreg.KEY_SET_VALUE]:
                    try:
                        with winreg.CreateKeyEx(root, p, 0, flag) as k:
                            winreg.SetValueEx(k, 'FilialPrecosPromocao', 0, winreg.REG_DWORD, filial_int)
                            updated = True
                            break
                    except Exception:
                        pass
        except Exception:
            pass
        return updated

    @staticmethod
    def get_table_columns(cur, table_name):
        try:
            cur.execute(f"SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE TRIM(RDB$RELATION_NAME) = '{table_name.upper()}'")
            return {r[0].strip().upper() for r in cur.fetchall()}
        except Exception:
            return set()

    @staticmethod
    def get_connection(config):
        host = config.get('host', 'localhost')
        port = config.get('port', 3050)
        db_path = config.get('db_path', '/SDSuper/Dados/SDSuper.fdb')
        user = config.get('user', 'SYSDBA')
        password = config.get('password', 'sdkey')
        dsn = f"{host}/{port}:{db_path}"
        return connect(dsn, user=user, password=password, charset="WIN1252")

    @staticmethod
    def test_and_load(config, orig_filial=1, dest_filial=2):
        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        
        # 1. Carregar Filiais
        cur.execute("SELECT WIDFILIAL, WFANTASIA, WRAZAO, WCNPJ FROM FILIAIS ORDER BY WIDFILIAL")
        filiais = []
        for r in cur.fetchall():
            filiais.append({
                "id": r[0],
                "fantasia": (r[1] or '').strip(),
                "razao": (r[2] or '').strip(),
                "cnpj": (r[3] or '').strip()
            })

        # 2. Carregar Usuários e status de permissão
        dest_str = f"{dest_filial:02d}"
        cur.execute("""
            SELECT U.WIDUSUARIO, U.WNOMEUSUARIO, U.WIDFILIAL, U.WIDFILIALTRABALHO, U.WFILIAISPDVS, U.WPERMISSOESPDVS, U.WTIPO
            FROM USUARIOS U
            WHERE (U.WSTATUS IS NULL OR U.WSTATUS = 'A')
              AND (U.WTIPO IS NULL OR U.WTIPO = 0)
            ORDER BY U.WNOMEUSUARIO
        """)
        user_rows = cur.fetchall()

        # Pré-carregar contagens de permissões por filial
        cur.execute(f"""
            SELECT WIDUSUARIO, WIDFILIAL, COUNT(*) 
            FROM PERMISSOES 
            WHERE WIDFILIAL IN ({orig_filial}, {dest_filial})
            GROUP BY WIDUSUARIO, WIDFILIAL
        """)
        perm_counts = {}
        for r in cur.fetchall():
            perm_counts[(r[0], r[1])] = r[2]

        SYSTEM_IGNORE_NAMES = {
            'ADMINISTRADOR', 'ACS AUTOMACAO', 'ACS AUTOMACAO COMERCIAL',
            'ETIQUETA', 'NORTH SISTEMAS', 'MASTER', 'COMANDA', 'RECEPCAO', 'SISTEMA ANTIGO'
        }

        users = []
        for r in user_rows:
            uid, nome, fil_padrao, fil_trab, fil_pdvs, perm_pdvs, tipo = r
            nome_str = (nome or '').strip()

            # Ocultar usuários de sistema, integrações e serviços SD
            norm_upper = unicodedata.normalize('NFKD', nome_str).encode('ASCII', 'ignore').decode('ASCII').upper().strip()
            if any(norm_upper.startswith(p) for p in ['SD ', 'SD_', 'SISTEMA ']):
                continue
            if norm_upper in SYSTEM_IGNORE_NAMES:
                continue

            pdvs_str = (fil_pdvs or '').strip() if fil_pdvs else ''
            perm_pdvs_str = (perm_pdvs or '').strip() if perm_pdvs else ''
            
            p_orig = perm_counts.get((uid, orig_filial), 0)
            p_dest = perm_counts.get((uid, dest_filial), 0)
            
            # Operador com permissões de PDV marcadas
            has_pdv_perms = bool(perm_pdvs_str)
            has_pdv_filial = bool(pdvs_str)
            pdv_has_dest = dest_str in pdvs_str if has_pdv_filial else False

            # Avaliar status em relação à filial destino
            perm_ok = (p_dest >= p_orig) if p_orig > 0 else True
            pdv_ok = pdv_has_dest if has_pdv_perms else True
            acesso_ok = (fil_trab == dest_filial)

            if perm_ok and pdv_ok and (p_dest > 0 or not has_pdv_perms):
                status = "OK"
            elif p_dest > 0 or pdv_has_dest or (acesso_ok and not perm_ok):
                status = "PARCIAL"
            else:
                status = "PENDENTE"

            users.append({
                "id": uid,
                "nome": nome_str,
                "tipo": tipo,
                "filial_padrao": fil_padrao,
                "filial_trabalho": fil_trab,
                "pdvs": pdvs_str if pdvs_str else None,
                "has_pdv_perms": has_pdv_perms,
                "has_pdv_filial": has_pdv_filial,
                "pdv_has_dest": pdv_has_dest,
                "perm_orig": p_orig,
                "perm_dest": p_dest,
                "status": status
            })

        # 3. Informações Estruturais de Migração (Filial Padrão, Produtos e Versão do Banco)
        gen_filial_padrao = None
        try:
            cur.execute("SELECT GEN_ID(GENIDFILIALPADRAO, 0) FROM RDB$DATABASE")
            gen_filial_padrao = cur.fetchone()[0]
        except Exception:
            pass

        widfilialprodutos = None
        try:
            cur.execute("SELECT WIDFILIALPRODUTOS FROM CONTROLE")
            r_cp = cur.fetchone()
            if r_cp:
                widfilialprodutos = r_cp[0]
        except Exception:
            pass

        filiais_controle = []
        max_versao_banco = None
        try:
            cur.execute("SELECT WIDFILIAL, WVERSAOBANCO, WULTIMOACESSO FROM FILIAISCONTROLE ORDER BY WIDFILIAL")
            fc_rows = cur.fetchall()
            for r in fc_rows:
                filiais_controle.append({
                    "filial": r[0],
                    "versao": r[1],
                    "ultimo_acesso": str(r[2]) if r[2] else None
                })
            v_list = [r[1] for r in fc_rows if r[1] is not None]
            if v_list:
                max_versao_banco = max(v_list)
        except Exception:
            pass

        # 4. Status de Promoções Ativas e Filiais
        promocoes_status = {
            "total_ativas": 0,
            "ativas_com_dest": 0,
            "ativas_sem_dest": 0,
            "promocoes": []
        }
        dest_tag = f"|{dest_filial}|"
        try:
            cur.execute("""
                SELECT WIDANTPROMOCAO, WNOMEPROMOCAO, WTIPO, WDATAINICIO, WDATATERMINO, WFILIAIS, WPRODUTOS
                FROM ANTPROMOCOES
                WHERE (WSTATUS IS NULL OR WSTATUS <> 'X')
                  AND WDATATERMINO >= CURRENT_TIMESTAMP
                ORDER BY WDATATERMINO DESC
            """)
            desc_p = [d[0] for d in cur.description]
            p_rows = cur.fetchall()
            for r in p_rows:
                p_dict = dict(zip(desc_p, r))
                wfil = (p_dict.get('WFILIAIS') or '').strip()
                has_dest = dest_tag in wfil
                promocoes_status["total_ativas"] += 1
                if has_dest:
                    promocoes_status["ativas_com_dest"] += 1
                else:
                    promocoes_status["ativas_sem_dest"] += 1

                promocoes_status["promocoes"].append({
                    "id": p_dict.get('WIDANTPROMOCAO'),
                    "nome": (p_dict.get('WNOMEPROMOCAO') or '').strip(),
                    "tipo": p_dict.get('WTIPO'),
                    "inicio": p_dict.get('WDATAINICIO').strftime('%d/%m/%Y') if p_dict.get('WDATAINICIO') else '',
                    "termino": p_dict.get('WDATATERMINO').strftime('%d/%m/%Y %H:%M') if p_dict.get('WDATATERMINO') else '',
                    "filiais": wfil,
                    "produtos": p_dict.get('WPRODUTOS') or 0,
                    "has_dest": has_dest
                })
        except Exception as e:
            promocoes_status["error"] = str(e)

        # 5. Filial de Preços das Promoções (Registro do Windows e Banco)
        filial_precos_promocao_reg = FirebirdManager.get_filial_precos_registry()
        widfilialprecos_banco = None
        try:
            cur.execute(f"SELECT WIDFILIALPRECOS FROM FILIAIS WHERE WIDFILIAL = {dest_filial}")
            r_fp = cur.fetchone()
            if r_fp:
                widfilialprecos_banco = r_fp[0]
        except Exception:
            pass

        conn.close()
        return {
            "success": True, 
            "filiais": filiais, 
            "users": users,
            "migration_status": {
                "gen_filial_padrao": gen_filial_padrao,
                "widfilialprodutos": widfilialprodutos,
                "max_versao_banco": max_versao_banco,
                "filiais_controle": filiais_controle,
                "promocoes_status": promocoes_status,
                "filial_precos_promocao_reg": filial_precos_promocao_reg,
                "widfilialprecos_banco": widfilialprecos_banco
            }
        }

    @staticmethod
    def execute_batch(config, payload):
        user_ids = payload.get('user_ids', [])
        orig_filial = int(payload.get('orig_filial', 1))
        dest_filial = int(payload.get('dest_filial', 2))
        opt_permissoes = payload.get('opt_permissoes', False)
        opt_pdvs = payload.get('opt_pdvs', False)
        opt_filial_acesso = payload.get('opt_filial_acesso', False)
        opt_preservar_outras = payload.get('opt_preservar_outras', True)
        opt_filial_cadastro = payload.get('opt_filial_cadastro', False)
        opt_gen_filial_padrao = payload.get('opt_gen_filial_padrao', False)
        opt_widfilialprodutos = payload.get('opt_widfilialprodutos', False)
        opt_sync_versaobanco = payload.get('opt_sync_versaobanco', False)
        opt_nfe_padrao = payload.get('opt_nfe_padrao', False)

        opt_promocoes_ativas = payload.get('opt_promocoes_ativas', False)
        opt_filial_precos_promocao = payload.get('opt_filial_precos_promocao', False)
        target_precos_promo_filial = int(payload.get('target_precos_promo_filial', dest_filial))

        target_gen_filial = int(payload.get('target_gen_filial', dest_filial))
        target_prod_filial = int(payload.get('target_prod_filial', dest_filial))
        target_acesso_filial = int(payload.get('target_acesso_filial', dest_filial))
        target_cadastro_filial = int(payload.get('target_cadastro_filial', dest_filial))
        target_versao_filial = int(payload.get('target_versao_filial', dest_filial))

        has_user_actions = (opt_permissoes or opt_pdvs or opt_filial_acesso or opt_filial_cadastro)
        has_system_actions = (opt_gen_filial_padrao or opt_widfilialprodutos or opt_sync_versaobanco or opt_nfe_padrao or opt_promocoes_ativas or opt_filial_precos_promocao)

        if not has_user_actions and not has_system_actions:
            return {"success": False, "error": "Selecione pelo menos uma opção de alteração."}

        if has_user_actions and not user_ids:
            return {"success": False, "error": "Selecione pelo menos 1 usuário para aplicar as alterações de permissões/filial de acesso."}

        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        dest_f_str = f"{dest_filial:02d}"

        logs = []
        system_actions_done = []
        total_perms_inserted = 0
        total_pdvs_updated = 0
        total_acesso_updated = 0
        total_cadastro_updated = 0
        total_promos_updated = 0
        total_prods_updated = 0

        try:
            # --- AÇÕES ESTRUTURAIS DE SISTEMA / BANCO ---
            # 1. Alterar ID Padrão do Sistema (GENIDFILIALPADRAO)
            if opt_gen_filial_padrao:
                cur.execute(f"SET GENERATOR GENIDFILIALPADRAO TO {target_gen_filial}")
                system_actions_done.append(f"ID Padrão do Sistema (GENIDFILIALPADRAO) alterado para Filial {target_gen_filial}.")

            # 2. Alterar Filial de Cadastro de Produtos (CONTROLE.WIDFILIALPRODUTOS)
            if opt_widfilialprodutos:
                cur.execute(f"UPDATE CONTROLE SET WIDFILIALPRODUTOS = {target_prod_filial}")
                system_actions_done.append(f"Filial de Cadastro de Produtos (CONTROLE.WIDFILIALPRODUTOS) alterada para Filial {target_prod_filial}.")

            # 3. Sincronizar Versão do Banco (FILIAISCONTROLE.WVERSAOBANCO)
            if opt_sync_versaobanco:
                cur.execute("SELECT MAX(WVERSAOBANCO) FROM FILIAISCONTROLE WHERE WVERSAOBANCO IS NOT NULL")
                row_max = cur.fetchone()
                max_v = row_max[0] if row_max else 11740
                cur.execute(f"""
                    UPDATE FILIAISCONTROLE 
                    SET WVERSAOBANCO = {max_v} 
                    WHERE WIDFILIAL = {target_versao_filial} OR WVERSAOBANCO IS NULL
                """)
                system_actions_done.append(f"Versão do Banco ({max_v}) sincronizada para Filial {target_versao_filial} na tabela FILIAISCONTROLE.")

            # 4. Configurar Parâmetros de NF-e Padrão (Série 0, Número 0, TecnoSpeed)
            if opt_nfe_padrao:
                target_f = target_versao_filial
                cur.execute(f"UPDATE FILIAISCONTROLE SET WNFESERIE = '0', WNFENUMERO = 0 WHERE WIDFILIAL = {target_f}")

                cur.execute("SELECT COUNT(*) FROM NFECONFIGURACAOFILIAIS WHERE WIDFILIAL = ?", (target_f,))
                exists_nfe = (cur.fetchone()[0] > 0)
                
                cur.execute("SELECT FIRST 1 WIDNFEAMBIENTE FROM NFEAMBIENTE ORDER BY WIDNFEAMBIENTE")
                r_amb = cur.fetchone()
                id_amb = r_amb[0] if r_amb else 11

                nfe_cols = FirebirdManager.get_table_columns(cur, 'NFECONFIGURACAOFILIAIS')

                defaults = {
                    'WIDNFEAMBIENTE': id_amb,
                    'WPRAZODOWNLOAD': 30,
                    'WNOMENCLATURAXML': 1,
                    'WULTIMONSU': 0,
                    'WCERTIFICADO': '123',
                    'WATIVARLOG': 'N',
                    'WNFESERIE': 0,
                    'WEMAILAUTOMATICO': 'S',
                    'WCOMPONENTE': 3,
                    'WIDPLANOPAGTONFCE': 1,
                    'WPFCP': 2.0,
                    'WRESTRICAOCSTCFOP': 'S',
                    'WCNPJSOFTWAREHOUSE': '04.260.756/0001-20',
                    'WAUDITOR': 1,
                    'WHTTPAUDITOR': 'http://validadornfe.tecnospeed.com.br:8181/validadorgui/validar',
                    'WVISUALIZARAUDITOR': 2,
                    'WCOMPONENTEEMISSAO': 3,
                    'WLIMITEINUTILIZACAO': 100,
                    'WMDFESERIE': 0,
                    'WAMBIENTE': 1,
                    'WALIQUOTADESONERACAO': 18.0,
                    'WREGRAFRETEDI': 1,
                    'WPERCMINIMOICMS': 0.0,
                    'WBAIXARXMLINVOICY': 'N',
                    'WDATAREFORMAPRODUCAO': '2026-06-30',
                    'WEMISSAOSINCRONA': 'S',
                    'WNFECONNECT': 'N'
                }

                if exists_nfe:
                    valid_updates = [f"{c} = COALESCE({c}, ?)" for c in defaults if c in nfe_cols]
                    if valid_updates:
                        set_str = ", ".join(valid_updates)
                        params = [defaults[c] for c in defaults if c in nfe_cols] + [target_f]
                        cur.execute(f"UPDATE NFECONFIGURACAOFILIAIS SET {set_str} WHERE WIDFILIAL = ?", tuple(params))
                else:
                    insert_map = {'WIDFILIAL': target_f}
                    for c, v in defaults.items():
                        if c in nfe_cols:
                            insert_map[c] = v
                    cols_str = ", ".join(insert_map.keys())
                    vals_str = ", ".join("?" for _ in insert_map)
                    cur.execute(f"INSERT INTO NFECONFIGURACAOFILIAIS ({cols_str}) VALUES ({vals_str})", tuple(insert_map.values()))

                system_actions_done.append(f"Parâmetros Fiscais de NF-e e TecnoSpeed configurados (Série 0, Número 0) para Filial {target_f}.")

            # 5. Incluir Nova Filial nas Promoções Ativas (ETAPA 1: Seguro Executar com Antecedência)
            if opt_promocoes_ativas:
                dest_tag = f"|{dest_filial}|"
                cur.execute("""
                    SELECT WIDANTPROMOCAO, WFILIAIS 
                    FROM ANTPROMOCOES 
                    WHERE (WSTATUS IS NULL OR WSTATUS <> 'X')
                      AND WDATATERMINO >= CURRENT_TIMESTAMP
                """)
                active_promos = cur.fetchall()

                for p_id, p_filiais in active_promos:
                    p_filiais_str = (p_filiais or '').strip()
                    if dest_tag not in p_filiais_str:
                        if not p_filiais_str:
                            new_filiais = f"|{orig_filial}|{dest_filial}|"
                        elif p_filiais_str.endswith('|'):
                            new_filiais = f"{p_filiais_str}{dest_filial}|"
                        else:
                            new_filiais = f"{p_filiais_str}|{dest_filial}|"
                        
                        cur.execute("""
                            UPDATE ANTPROMOCOES 
                            SET WFILIAIS = ?, WUPDATETIME = CURRENT_TIMESTAMP 
                            WHERE WIDANTPROMOCAO = ?
                        """, (new_filiais, p_id))
                        total_promos_updated += 1

                    # Atualizar produtos da promoção
                    cur.execute("""
                        SELECT WIDANTPRODUTO, WFILIAIS 
                        FROM ANTPRODUTOS 
                        WHERE WIDANTPROMOCAO = ? AND (WSTATUS IS NULL OR WSTATUS <> 'X')
                    """, (p_id,))
                    prods = cur.fetchall()
                    for pr_id, pr_fil in prods:
                        pr_fil_str = (pr_fil or '').strip()
                        new_pr_fil = pr_fil_str
                        if dest_tag not in pr_fil_str:
                            if not pr_fil_str:
                                new_pr_fil = f"|{orig_filial}|{dest_filial}|"
                            elif pr_fil_str.endswith('|'):
                                new_pr_fil = f"{pr_fil_str}{dest_filial}|"
                            else:
                                new_pr_fil = f"{pr_fil_str}|{dest_filial}|"

                        if dest_filial <= 10:
                            wfil_col = f"WFIL{dest_filial}"
                            cur.execute(f"""
                                UPDATE ANTPRODUTOS 
                                SET WFILIAIS = ?, {wfil_col} = 'S', WUPDATETIME = CURRENT_TIMESTAMP 
                                WHERE WIDANTPRODUTO = ?
                            """, (new_pr_fil, pr_id))
                        else:
                            cur.execute("""
                                UPDATE ANTPRODUTOS 
                                SET WFILIAIS = ?, WUPDATETIME = CURRENT_TIMESTAMP 
                                WHERE WIDANTPRODUTO = ?
                            """, (new_pr_fil, pr_id))
                        total_prods_updated += 1

                # Replicar modelos de etiquetas promocionais se ainda não existirem para dest_filial
                try:
                    cur.execute("SELECT WTIPOPROMOCAO, WIDMODELO FROM ETIQUETASMODELOPROMOCAO WHERE WIDFILIAL = ?", (orig_filial,))
                    orig_etiquetas = cur.fetchall()
                    for tipo_p, id_mod in orig_etiquetas:
                        cur.execute("SELECT COUNT(*) FROM ETIQUETASMODELOPROMOCAO WHERE WIDFILIAL = ? AND WTIPOPROMOCAO = ?", (dest_filial, tipo_p))
                        if cur.fetchone()[0] == 0:
                            cur.execute("""
                                INSERT INTO ETIQUETASMODELOPROMOCAO (WIDFILIAL, WTIPOPROMOCAO, WIDMODELO)
                                VALUES (?, ?, ?)
                            """, (dest_filial, tipo_p, id_mod))
                except Exception:
                    pass

                system_actions_done.append(
                    f"Promoções Ativas: Filial {dest_filial} incluída com sucesso ({total_promos_updated} promoções e {total_prods_updated} itens atualizados em ANTPROMOCOES/ANTPRODUTOS)."
                )

            # 6. Troca da Filial de Preços da Promoção (ETAPA 2: Momento da Virada Oficial)
            if opt_filial_precos_promocao:
                target_p_filial = int(target_precos_promo_filial)
                FirebirdManager.set_filial_precos_registry(target_p_filial)
                try:
                    cur.execute("UPDATE FILIAIS SET WIDFILIALPRECOS = ? WHERE WIDFILIAL = ?", (target_p_filial, dest_filial))
                except Exception:
                    pass
                system_actions_done.append(
                    f"Filial de Preços das Promoções (FilialPrecosPromocao) definida para Filial {target_p_filial} no Registro do Windows e em FILIAIS.WIDFILIALPRECOS."
                )
            for uid in user_ids:
                u_log = {"id": uid, "actions": []}

                # 1. Obter dados atuais do usuário
                cur.execute(f"SELECT WNOMEUSUARIO, WFILIAISPDVS, WIDFILIAL, WIDFILIALTRABALHO, WPERMISSOESPDVS FROM USUARIOS WHERE WIDUSUARIO = {uid}")
                urow = cur.fetchone()
                if not urow:
                    u_log["actions"].append("Usuário não encontrado.")
                    logs.append(u_log)
                    continue

                unome, old_pdvs, old_fil, old_trab, perm_pdvs = urow
                unome = (unome or '').strip()
                perm_pdvs_str = (perm_pdvs or '').strip() if perm_pdvs else ''
                has_pdv_perms = bool(perm_pdvs_str)
                u_log["nome"] = unome

                # 2. Replicar Permissões SDSuper se selecionado
                if opt_permissoes:
                    cur.execute(f"""
                        SELECT WTIPOPERMISSAO, WACESSO, WPERMISSAO 
                        FROM PERMISSOES 
                        WHERE WIDUSUARIO = {uid} AND WIDFILIAL = {orig_filial}
                    """)
                    orig_perms = cur.fetchall()
                    source_filial_used = orig_filial

                    # Se não possui permissões na filial origem, mas opera em outra filial (ex: F3, F4)
                    if not orig_perms and old_trab and old_trab != orig_filial and old_trab != dest_filial:
                        cur.execute(f"""
                            SELECT WTIPOPERMISSAO, WACESSO, WPERMISSAO 
                            FROM PERMISSOES 
                            WHERE WIDUSUARIO = {uid} AND WIDFILIAL = {old_trab}
                        """)
                        perms_from_trab = cur.fetchall()
                        if perms_from_trab:
                            orig_perms = perms_from_trab
                            source_filial_used = old_trab
                    
                    inserted_this_user = 0
                    for p in orig_perms:
                        wtipoperm, wacesso, wperm = p
                        # Checar se já existe na filial destino
                        cur.execute(f"""
                            SELECT COUNT(*) FROM PERMISSOES 
                            WHERE WIDUSUARIO = {uid} AND WIDFILIAL = {dest_filial} AND WTIPOPERMISSAO = {wtipoperm}
                        """)
                        if cur.fetchone()[0] == 0:
                            # Gerador do SDSuper: (GEN_ID * 10) + 1
                            cur.execute("SELECT GEN_ID(GENIDPERMISSAO, 1) FROM RDB$DATABASE")
                            gen_val = cur.fetchone()[0]
                            new_id = (gen_val * 10) + 1

                            cur.execute("""
                                INSERT INTO PERMISSOES (WIDPERMISSAO, WIDUSUARIO, WIDFILIAL, WPERMISSAO, WACESSO, WTIPOPERMISSAO)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (new_id, uid, dest_filial, wperm, wacesso, wtipoperm))
                            inserted_this_user += 1

                    if inserted_this_user > 0:
                        u_log["actions"].append(f"+{inserted_this_user} permissões clonadas (base F{source_filial_used}) para Filial {dest_filial}.")
                        total_perms_inserted += inserted_this_user
                    else:
                        u_log["actions"].append("Permissões de SDSuper já sincronizadas ou inexistentes no modelo.")

                # 3. Adicionar Filial no PDV (EXCLUSIVAMENTE se possuir permissões de PDV ativas!)
                if opt_pdvs:
                    if not has_pdv_perms:
                        u_log["actions"].append("Sem permissões na grade de PDVs (ignorado para não aparecer no caixa).")
                    else:
                        old_pdvs_str = (old_pdvs or '').strip()
                        if not old_pdvs_str:
                            new_pdvs_str = dest_f_str
                            cur.execute("""
                                UPDATE USUARIOS 
                                SET WFILIAISPDVS = ? 
                                WHERE WIDUSUARIO = ?
                            """, (new_pdvs_str, uid))
                            u_log["actions"].append(f"PDV definido como '{new_pdvs_str}'.")
                            total_pdvs_updated += 1
                        elif dest_f_str not in old_pdvs_str:
                            new_pdvs_str = dest_f_str + old_pdvs_str
                            cur.execute("""
                                UPDATE USUARIOS 
                                SET WFILIAISPDVS = ? 
                                WHERE WIDUSUARIO = ?
                            """, (new_pdvs_str, uid))
                            u_log["actions"].append(f"PDV atualizado de '{old_pdvs_str}' para '{new_pdvs_str}'.")
                            total_pdvs_updated += 1
                        else:
                            u_log["actions"].append("PDV já possuía a filial cadastrada.")

                # 4. Alterar "Filial Acesso" (WIDFILIALTRABALHO) para a nova filial
                if opt_filial_acesso:
                    if opt_preservar_outras and old_trab and old_trab != orig_filial and old_trab != target_acesso_filial:
                        u_log["actions"].append(f"Filial Acesso mantida em F{old_trab} (opera fixo em outra loja).")
                    elif old_trab != target_acesso_filial:
                        cur.execute("""
                            UPDATE USUARIOS 
                            SET WIDFILIALTRABALHO = ? 
                            WHERE WIDUSUARIO = ?
                        """, (target_acesso_filial, uid))
                        u_log["actions"].append(f"Filial Acesso alterada de {old_trab or 0} para {target_acesso_filial}.")
                        total_acesso_updated += 1
                    else:
                        u_log["actions"].append(f"Filial Acesso já era {target_acesso_filial}.")

                # 5. Alterar "Filial Cadastro" (WIDFILIAL) se selecionado
                if opt_filial_cadastro:
                    if old_fil != target_cadastro_filial:
                        cur.execute("""
                            UPDATE USUARIOS 
                            SET WIDFILIAL = ? 
                            WHERE WIDUSUARIO = ?
                        """, (target_cadastro_filial, uid))
                        u_log["actions"].append(f"Filial Cadastro alterada de {old_fil} para {target_cadastro_filial}.")
                        total_cadastro_updated += 1
                    else:
                        u_log["actions"].append(f"Filial Cadastro já era {target_cadastro_filial}.")

                logs.append(u_log)

            # Efetivar transação
            conn.commit()
            conn.close()
            return {
                "success": True,
                "summary": {
                    "total_users": len(user_ids),
                    "perms_inserted": total_perms_inserted,
                    "pdvs_updated": total_pdvs_updated,
                    "acesso_updated": total_acesso_updated,
                    "cadastro_updated": total_cadastro_updated,
                    "promocoes_updated": total_promos_updated,
                    "system_actions": system_actions_done
                },
                "logs": logs
            }
        except Exception as e:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_local_ip():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('10.255.255.255', 1))
            ip = s.getsockname()[0]
        except Exception:
            try:
                ip = socket.gethostbyname(socket.gethostname())
            except Exception:
                ip = '127.0.0.1'
        finally:
            s.close()
        return ip

    @staticmethod
    def get_database_ip(config=None):
        """
        Retorna o IP do Servidor do Banco de Dados para onde os PDVs devem se conectar.
        - Se o banco está numa VM Linux ou servidor na rede (ex: 10.0.0.112), retorna esse IP.
        - Se o host for localhost / 127.0.0.1 ou vazio, o banco está local no Windows:
          Nesse caso, os PDVs precisam do IP de rede (LAN) desta máquina (FirebirdManager.get_local_ip()).
        - Se houver IP no Registro do Windows (ex: VM Linux), utiliza-o se host for localhost.
        """
        host = None
        if config and isinstance(config, dict):
            host = config.get('host')

        if not host or not str(host).strip():
            try:
                reg = FirebirdManager.detect_registry()
                if reg and reg.get('found') and reg.get('raw_ip'):
                    host = reg.get('raw_ip')
            except Exception:
                pass

        host_str = str(host or '').strip()

        # Se for localhost ou 127.0.0.1 ou vazio
        if not host_str or host_str.lower() in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
            # Verifica se no Registro do Windows tem um IP de servidor específico (ex: VM Linux)
            try:
                reg = FirebirdManager.detect_registry()
                if reg and reg.get('found') and reg.get('raw_ip'):
                    reg_raw = str(reg.get('raw_ip')).strip()
                    if reg_raw and reg_raw.lower() not in ('localhost', '127.0.0.1', '::1', '0.0.0.0'):
                        return reg_raw
            except Exception:
                pass
            return FirebirdManager.get_local_ip()

        # Se já for formato IPv4 numérico (ex: 10.0.0.112)
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host_str):
            return host_str

        # Se for um hostname/DDNS (ex: precobaixogo.ddns.com.br), tenta resolver para IP numérico
        try:
            resolved = socket.gethostbyname(host_str)
            if resolved and resolved not in ('127.0.0.1', '0.0.0.0'):
                return resolved
        except Exception:
            pass

        return host_str


    @staticmethod
    def format_cep(cep_raw):
        if not cep_raw:
            return ""
        # Remove pontos e caracteres não-numéricos, mantendo apenas dígitos
        digits = re.sub(r'\D', '', str(cep_raw))
        if len(digits) >= 8:
            return f"{digits[:5]}-{digits[5:8]}"
        elif len(digits) > 5:
            return f"{digits[:5]}-{digits[5:]}"
        return digits

    @staticmethod
    def consult_cnpj_api(cnpj_raw):
        cnpj_clean = re.sub(r'\D', '', str(cnpj_raw or ''))
        if len(cnpj_clean) != 14:
            return {"success": False, "error": "CNPJ deve conter 14 dígitos numéricos."}
        
        # 1. Tentar BrasilAPI
        try:
            url = f"https://brasilapi.com.br/api/cnpj/v1/{cnpj_clean}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    return {
                        "success": True,
                        "source": "BrasilAPI",
                        "razao": (data.get("razao_social") or "").strip(),
                        "fantasia": (data.get("nome_fantasia") or data.get("razao_social") or "").strip(),
                        "cnpj": (data.get("cnpj") or cnpj_clean).strip(),
                        "cep": FirebirdManager.format_cep(data.get("cep") or ""),
                        "logradouro": f"{data.get('descricao_tipo_de_logradouro', '')} {data.get('logradouro', '')}".strip(),
                        "numero": (data.get("numero") or "").strip(),
                        "complemento": (data.get("complemento") or "").strip(),
                        "bairro": (data.get("bairro") or "").strip(),
                        "municipio": (data.get("municipio") or "").strip(),
                        "uf": (data.get("uf") or "").strip(),
                        "ibge": str(data.get("codigo_municipio_ibge") or "").strip(),
                        "email": (data.get("email") or "").strip(),
                        "telefone": (data.get("ddd_telefone_1") or "").strip()
                    }
        except Exception:
            pass

        # 2. Fallback ReceitaWS
        try:
            url = f"https://receitaws.com.br/v1/cnpj/{cnpj_clean}"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode('utf-8'))
                    if data.get("status") == "OK":
                        return {
                            "success": True,
                            "source": "ReceitaWS",
                            "razao": (data.get("nome") or "").strip(),
                            "fantasia": (data.get("fantasia") or data.get("nome") or "").strip(),
                            "cnpj": (data.get("cnpj") or cnpj_clean).strip(),
                            "cep": FirebirdManager.format_cep(data.get("cep") or ""),
                            "logradouro": (data.get("logradouro") or "").strip(),
                            "numero": (data.get("numero") or "").strip(),
                            "complemento": (data.get("complemento") or "").strip(),
                            "bairro": (data.get("bairro") or "").strip(),
                            "municipio": (data.get("municipio") or "").strip(),
                            "uf": (data.get("uf") or "").strip(),
                            "ibge": "",
                            "email": (data.get("email") or "").strip(),
                            "telefone": (data.get("telefone") or "").strip()
                        }
        except Exception:
            pass

        return {"success": False, "error": "Não foi possível consultar os dados do CNPJ nas APIs públicas."}

    @staticmethod
    def normalize_text(text):
        if not text:
            return ""
        return unicodedata.normalize('NFKD', str(text)).encode('ASCII', 'ignore').decode('ASCII').strip().upper()

    @staticmethod
    def resolve_cidade(cur, cidade_val, cidade_nome=None, uf=None, ibge=None):
        """
        Resolve assertivamente a cidade na tabela CIDADES do Firebird vinculando com ESTADOS.
        Evita a todo custo falsos positivos e a atribuição indevida da cidade padrão (Cabo Frio - ID 6).
        """
        c_norm = FirebirdManager.normalize_text(cidade_nome or (cidade_val if not str(cidade_val).isdigit() else "") or "")
        uf_clean = str(uf or "").strip().upper()[:2]
        
        # 1. Se fornecido código IBGE oficial de 7 dígitos
        if ibge and str(ibge).isdigit() and int(ibge) > 0:
            cur.execute("""
                SELECT C.WIDCIDADE, C.WNOMECIDADE, E.WSIGLA, C.WIBGE
                FROM CIDADES C
                LEFT JOIN ESTADOS E ON E.WIDESTADO = C.WIDESTADO
                WHERE C.WIBGE = ?
            """, (int(ibge),))
            r = cur.fetchone()
            if r:
                return {
                    "found": True, 
                    "id": r[0], 
                    "nome": (r[1] or '').strip().upper(), 
                    "uf": (r[2] or '').strip().upper(), 
                    "ibge": r[3], 
                    "match": "ibge"
                }

        # 2. Se cidade_val é um ID numérico pré-existente, verificar se o nome do banco bate com o nome desejado
        if cidade_val and str(cidade_val).isdigit() and int(cidade_val) > 0:
            cur.execute("""
                SELECT C.WIDCIDADE, C.WNOMECIDADE, E.WSIGLA, C.WIBGE
                FROM CIDADES C
                LEFT JOIN ESTADOS E ON E.WIDESTADO = C.WIDESTADO
                WHERE C.WIDCIDADE = ?
            """, (int(cidade_val),))
            r = cur.fetchone()
            if r:
                db_norm = FirebirdManager.normalize_text(r[1])
                # Se não temos c_norm OU se o nome bate, aceita
                if not c_norm or db_norm == c_norm:
                    return {
                        "found": True, 
                        "id": r[0], 
                        "nome": (r[1] or '').strip().upper(), 
                        "uf": (r[2] or '').strip().upper(), 
                        "ibge": r[3], 
                        "match": "id_match"
                    }
                # Se o nome NÃO bate (ex: ID guardava 6/Cabo Frio mas agora o texto é RIO DE JANEIRO),
                # descartamos o ID obsoleto e resolvemos por nome/UF abaixo.

        target_name = (cidade_nome or (cidade_val if not str(cidade_val).isdigit() else "") or "").strip()
        if not target_name:
            return {"found": False, "id": None, "nome": "", "uf": uf_clean, "error": "Nome da cidade não informado."}

        target_clean = target_name[:35].upper()

        # 3. Match exato com Nome e UF (CIDADES + ESTADOS)
        if uf_clean:
            cur.execute("""
                SELECT C.WIDCIDADE, C.WNOMECIDADE, E.WSIGLA, C.WIBGE
                FROM CIDADES C
                LEFT JOIN ESTADOS E ON E.WIDESTADO = C.WIDESTADO
                WHERE UPPER(TRIM(C.WNOMECIDADE)) = UPPER(TRIM(?))
                  AND UPPER(TRIM(E.WSIGLA)) = UPPER(TRIM(?))
            """, (target_clean, uf_clean))
            r = cur.fetchone()
            if r:
                return {
                    "found": True, 
                    "id": r[0], 
                    "nome": (r[1] or '').strip().upper(), 
                    "uf": (r[2] or '').strip().upper(), 
                    "ibge": r[3], 
                    "match": "exact_uf"
                }

        # 4. Match com normalização de acentos filtrando pela UF (ex: 'NITEROI' -> 'NITERÓI')
        if uf_clean:
            cur.execute("""
                SELECT C.WIDCIDADE, C.WNOMECIDADE, E.WSIGLA, C.WIBGE
                FROM CIDADES C
                LEFT JOIN ESTADOS E ON E.WIDESTADO = C.WIDESTADO
                WHERE UPPER(TRIM(E.WSIGLA)) = UPPER(TRIM(?))
            """, (uf_clean,))
            for r in cur.fetchall():
                if FirebirdManager.normalize_text(r[1]) == c_norm:
                    return {
                        "found": True, 
                        "id": r[0], 
                        "nome": (r[1] or '').strip().upper(), 
                        "uf": (r[2] or '').strip().upper(), 
                        "ibge": r[3], 
                        "match": "accent_norm_uf"
                    }

        # 5. Match sem UF (se UF não foi fornecida)
        if not uf_clean:
            cur.execute("""
                SELECT C.WIDCIDADE, C.WNOMECIDADE, E.WSIGLA, C.WIBGE
                FROM CIDADES C
                LEFT JOIN ESTADOS E ON E.WIDESTADO = C.WIDESTADO
                WHERE UPPER(TRIM(C.WNOMECIDADE)) = UPPER(TRIM(?))
            """, (target_clean,))
            rows = cur.fetchall()
            if len(rows) == 1:
                r = rows[0]
                return {
                    "found": True, 
                    "id": r[0], 
                    "nome": (r[1] or '').strip().upper(), 
                    "uf": (r[2] or '').strip().upper(), 
                    "ibge": r[3], 
                    "match": "exact_no_uf"
                }

        # 6. Não localizada
        uf_suffix = f" ({uf_clean})" if uf_clean else ""
        return {
            "found": False, 
            "id": None, 
            "nome": target_name, 
            "uf": uf_clean, 
            "error": f"Cidade '{target_name}'{uf_suffix} não foi localizada na tabela CIDADES do banco de dados deste cliente."
        }

    @staticmethod
    def resolve_or_create_bairro(cur, bairro_name):
        if not bairro_name:
            return None
        name_clean = str(bairro_name).strip()[:35]
        if not name_clean:
            return None
        cur.execute("SELECT WIDBAIRRO FROM BAIRROS WHERE UPPER(TRIM(WNOMEBAIRRO)) = UPPER(TRIM(?))", (name_clean,))
        r = cur.fetchone()
        if r:
            return r[0]
        cur.execute("SELECT GEN_ID(GENIDBAIRRO, 1) FROM RDB$DATABASE")
        gen_val = cur.fetchone()[0]
        new_id = (gen_val * 10) + 1
        cur.execute("INSERT INTO BAIRROS (WIDBAIRRO, WNOMEBAIRRO, WSTATUS, WUPDATETIME) VALUES (?, ?, 'A', CURRENT_TIMESTAMP)", (new_id, name_clean.upper()))
        return new_id

    @staticmethod
    def get_filial_details(config, filial_id=2):
        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        
        # 1. Lista de todas as filiais
        cur.execute("SELECT WIDFILIAL, WFANTASIA, WRAZAO, WCNPJ FROM FILIAIS ORDER BY WIDFILIAL")
        filiais_list = []
        for r in cur.fetchall():
            filiais_list.append({
                "id": r[0],
                "fantasia": (r[1] or '').strip(),
                "razao": (r[2] or '').strip(),
                "cnpj": (r[3] or '').strip()
            })
            
        local_ip = FirebirdManager.get_local_ip()
        db_ip = FirebirdManager.get_database_ip(config)
        suggested_terminal = f"\\\\{db_ip}\\SDPROGS$\\SDTERMINAL\\"
        suggested_ippdv = db_ip
        is_linux_db = bool(str(config.get('db_path', '')).startswith('/') or (FirebirdManager.detect_registry().get('is_linux', False)))

        # 2. Dados da filial solicitada
        cur.execute("""
            SELECT 
                F.WIDFILIAL, F.WRAZAO, F.WFANTASIA, F.WCNPJ, F.WINSCRICAOESTADUAL, F.WCONTATO, F.WNOMEREPRESENTANTE, F.WEMAIL, F.WTELEFONEGERAL,
                F.WENDERECO, F.WNUMERO, F.WCOMPLEMENTO, F.WCEP, F.WIDCIDADE, F.WIDBAIRRO,
                F.WNOMECONTADOR, F.WCNPJCONTADOR, F.WCPFCONTADOR, F.WCRCCONTADOR, F.WEMAILCONTADOR, F.WTELEFONECONTADOR,
                F.WENDERECOCONTADOR, F.WNUMEROCONTADOR, F.WCOMPLEMENTOCONTADOR, F.WCEPCONTADOR, F.WIDCIDADECONTADOR, F.WIDBAIRROCONTADOR,
                F.WIDFILIALPRECOS, F.WIDFILIALESTOQUE, F.WIDFILIALNFE, F.WIDFILIALSAIDASFISCAIS, F.WIDFILIALTRANSF, F.WIDFILIALMOVIMENTO, F.WIDFILIALETIQ, F.WIDFILIALCOMANDA,
                F.WIDFILIALCARGA,
                F.WCAMINHOSDTERMINAL, F.WIPPDV,
                C.WNOMECIDADE, E.WSIGLA, C.WIBGE,
                B.WNOMEBAIRRO,
                CC.WNOMECIDADE, ECC.WSIGLA, CC.WIBGE,
                CB.WNOMEBAIRRO
            FROM FILIAIS F
            LEFT JOIN CIDADES C ON C.WIDCIDADE = F.WIDCIDADE
            LEFT JOIN ESTADOS E ON E.WIDESTADO = C.WIDESTADO
            LEFT JOIN BAIRROS B ON B.WIDBAIRRO = F.WIDBAIRRO
            LEFT JOIN CIDADES CC ON CC.WIDCIDADE = F.WIDCIDADECONTADOR
            LEFT JOIN ESTADOS ECC ON ECC.WIDESTADO = CC.WIDESTADO
            LEFT JOIN BAIRROS CB ON CB.WIDBAIRRO = F.WIDBAIRROCONTADOR
            WHERE F.WIDFILIAL = ?
        """, (filial_id,))
        row = cur.fetchone()

        # 3. Dados do contador da Filial 1 (para o facilitador de cópia)
        contador_filial_1 = None
        if filial_id != 1:
            cur.execute("""
                SELECT 
                    F.WNOMECONTADOR, F.WCNPJCONTADOR, F.WCPFCONTADOR, F.WCRCCONTADOR, F.WEMAILCONTADOR, F.WTELEFONECONTADOR,
                    F.WENDERECOCONTADOR, F.WNUMEROCONTADOR, F.WCOMPLEMENTOCONTADOR, F.WCEPCONTADOR, F.WIDCIDADECONTADOR, F.WIDBAIRROCONTADOR,
                    CC.WNOMECIDADE, ECC.WSIGLA, CB.WNOMEBAIRRO, CC.WIBGE
                FROM FILIAIS F
                LEFT JOIN CIDADES CC ON CC.WIDCIDADE = F.WIDCIDADECONTADOR
                LEFT JOIN ESTADOS ECC ON ECC.WIDESTADO = CC.WIDESTADO
                LEFT JOIN BAIRROS CB ON CB.WIDBAIRRO = F.WIDBAIRROCONTADOR
                WHERE F.WIDFILIAL = 1
            """)
            r1 = cur.fetchone()
            if r1:
                contador_filial_1 = {
                    "nome_contador": (r1[0] or '').strip().upper(),
                    "cnpj_contador": (r1[1] or '').strip().upper(),
                    "cpf_contador": (r1[2] or '').strip(),
                    "crc_contador": (r1[3] or '').strip().upper(),
                    "email_contador": (r1[4] or '').strip().upper(),
                    "telefone_contador": (r1[5] or '').strip(),
                    "endereco_contador": (r1[6] or '').strip().upper(),
                    "numero_contador": (r1[7] or '').strip().upper(),
                    "complemento_contador": (r1[8] or '').strip().upper(),
                    "cep_contador": FirebirdManager.format_cep(r1[9]),
                    "id_cidade_contador": r1[10],
                    "id_bairro_contador": r1[11],
                    "cidade_contador_nome": (r1[12] or '').strip().upper(),
                    "cidade_contador_uf": (r1[13] or '').strip().upper(),
                    "bairro_contador_nome": (r1[14] or '').strip().upper(),
                    "cidade_contador_ibge": r1[15]
                }

        conn.close()

        if not row:
            max_id = max([f['id'] for f in filiais_list], default=0)
            return {
                "success": True,
                "found": False,
                "filial_id": filial_id,
                "next_suggested_id": max_id + 1,
                "filiais_list": filiais_list,
                "contador_filial_1": contador_filial_1,
                "local_ip": local_ip,
                "database_ip": db_ip,
                "is_linux": is_linux_db,
                "suggested_terminal": suggested_terminal,
                "suggested_ippdv": suggested_ippdv,
                "ip_pdv": suggested_ippdv,
                "caminho_terminal": suggested_terminal,
                "ip_pdv_divergent": False,
                "filial_precos": 1,
                "filial_estoque": 1,
                "filial_nfe": filial_id,
                "filial_saidasfiscais": filial_id,
                "filial_transf": filial_id,
                "filial_movimento": filial_id,
                "filial_etiq": 1,
                "filial_comanda": 1,
                "filial_carga": filial_id
            }

        raw_caminho = (row[36] or '').strip()
        raw_ip_pdv = (row[37] or '').strip()
        
        # Se ip_pdv estiver vazio ou for 127.0.0.1 / localhost, usa db_ip
        effective_ip_pdv = raw_ip_pdv if (raw_ip_pdv and raw_ip_pdv.lower() not in ('127.0.0.1', 'localhost', '::1', '0.0.0.0')) else db_ip
        effective_caminho = raw_caminho if raw_caminho else suggested_terminal
        ip_pdv_divergent = bool(raw_ip_pdv and raw_ip_pdv != db_ip)

        return {
            "success": True,
            "found": True,
            "filial_id": row[0],
            "razao": (row[1] or '').strip().upper(),
            "fantasia": (row[2] or '').strip().upper(),
            "cnpj": (row[3] or '').strip().upper(),
            "ie": (row[4] or '').strip().upper(),
            "contato": (row[5] or '').strip().upper(),
            "representante": (row[6] or '').strip().upper(),
            "email": (row[7] or '').strip().upper(),
            "telefone": (row[8] or '').strip(),
            "endereco": (row[9] or '').strip().upper(),
            "numero": (row[10] or '').strip().upper(),
            "complemento": (row[11] or '').strip().upper(),
            "cep": FirebirdManager.format_cep(row[12]),
            "id_cidade": row[13],
            "id_bairro": row[14],
            "nome_contador": (row[15] or '').strip().upper(),
            "cnpj_contador": (row[16] or '').strip().upper(),
            "cpf_contador": (row[17] or '').strip(),
            "crc_contador": (row[18] or '').strip().upper(),
            "email_contador": (row[19] or '').strip().upper(),
            "telefone_contador": (row[20] or '').strip(),
            "endereco_contador": (row[21] or '').strip().upper(),
            "numero_contador": (row[22] or '').strip().upper(),
            "complemento_contador": (row[23] or '').strip().upper(),
            "cep_contador": FirebirdManager.format_cep(row[24]),
            "id_cidade_contador": row[25],
            "id_bairro_contador": row[26],
            "filial_precos": row[27] if row[27] is not None else 1,
            "filial_estoque": row[28] if row[28] is not None else 1,
            "filial_nfe": row[29] if row[29] is not None else row[0],
            "filial_saidasfiscais": row[30] if row[30] is not None else row[0],
            "filial_transf": row[31] if row[31] is not None else row[0],
            "filial_movimento": row[32] if row[32] is not None else row[0],
            "filial_etiq": row[33] if row[33] is not None else 1,
            "filial_comanda": row[34] if row[34] is not None else 1,
            "filial_carga": row[35] if row[35] is not None else row[0],
            "caminho_terminal": effective_caminho.upper(),
            "ip_pdv": effective_ip_pdv,
            "raw_ip_pdv": raw_ip_pdv,
            "ip_pdv_divergent": ip_pdv_divergent,
            "cidade_nome": (row[38] or '').strip().upper(),
            "cidade_uf": (row[39] or '').strip().upper(),
            "cidade_ibge": row[40],
            "bairro_nome": (row[41] or '').strip().upper(),
            "cidade_contador_nome": (row[42] or '').strip().upper(),
            "cidade_contador_uf": (row[43] or '').strip().upper(),
            "cidade_contador_ibge": row[44],
            "bairro_contador_nome": (row[45] or '').strip().upper(),
            "contador_filial_1": contador_filial_1,
            "filiais_list": filiais_list,
            "local_ip": local_ip,
            "database_ip": db_ip,
            "is_linux": is_linux_db,
            "suggested_terminal": suggested_terminal,
            "suggested_ippdv": suggested_ippdv
        }

    @staticmethod
    def save_filial_full(config, payload):
        filial_id = int(payload.get('filial_id', 2))
        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        try:
            # Resolver cidades e bairros com acertividade rigorosa
            cidade_val = payload.get('id_cidade')
            cidade_nome = payload.get('cidade_nome')
            cidade_uf = payload.get('cidade_uf')
            
            res_cidade = FirebirdManager.resolve_cidade(cur, cidade_val, cidade_nome, cidade_uf)
            if not res_cidade.get('found') or not res_cidade.get('id'):
                conn.close()
                target_desc = f"'{cidade_nome or cidade_val}'"
                if cidade_uf:
                    target_desc += f" ({cidade_uf})"
                return {
                    "success": False,
                    "error": (
                        f"❌ ACERTIVIDADE DE CIDADE: A cidade {target_desc} NÃO foi localizada na tabela CIDADES do banco de dados deste cliente!\n\n"
                        f"⚠️ Ação necessária: Para evitar erros fiscais e impedir que o sistema aplique uma cidade indevida (como Cabo Frio), "
                        f"verifique a grafia e a UF ou realize o cadastro da cidade no SDSuper (Tabelas > Cidades) antes de gravar a filial."
                    )
                }
            id_cidade = res_cidade['id']
            
            bairro_val = payload.get('id_bairro')
            bairro_nome = payload.get('bairro_nome')
            if bairro_val and str(bairro_val).isdigit() and int(bairro_val) > 0:
                id_bairro = int(bairro_val)
            else:
                id_bairro = FirebirdManager.resolve_or_create_bairro(cur, str(bairro_nome or '').upper())
                
            cidade_cont_val = payload.get('id_cidade_contador')
            cidade_cont_nome = payload.get('cidade_contador_nome')
            cidade_cont_uf = payload.get('cidade_contador_uf')
            
            id_cidade_cont = None
            if cidade_cont_nome or (cidade_cont_val and str(cidade_cont_val).isdigit()):
                res_cont = FirebirdManager.resolve_cidade(cur, cidade_cont_val, cidade_cont_nome, cidade_cont_uf)
                if not res_cont.get('found') or not res_cont.get('id'):
                    conn.close()
                    target_cont_desc = f"'{cidade_cont_nome or cidade_cont_val}'"
                    if cidade_cont_uf:
                        target_cont_desc += f" ({cidade_cont_uf})"
                    return {
                        "success": False,
                        "error": (
                            f"❌ ACERTIVIDADE DE CIDADE (CONTADOR): A cidade do contador {target_cont_desc} "
                            f"NÃO existe na tabela CIDADES do banco deste cliente!\n\n"
                            f"Verifique a grafia/UF ou cadastre a cidade no SDSuper antes de prosseguir."
                        )
                    }
                id_cidade_cont = res_cont['id']
            
            bairro_cont_val = payload.get('id_bairro_contador')
            bairro_cont_nome = payload.get('bairro_contador_nome')
            if bairro_cont_val and str(bairro_cont_val).isdigit() and int(bairro_cont_val) > 0:
                id_bairro_cont = int(bairro_cont_val)
            else:
                id_bairro_cont = FirebirdManager.resolve_or_create_bairro(cur, str(bairro_cont_nome or '').upper())

            local_ip = FirebirdManager.get_local_ip()
            db_ip = FirebirdManager.get_database_ip(config)
            
            caminho_terminal = (payload.get('caminho_terminal') or '').strip()
            if not caminho_terminal:
                caminho_terminal = f"\\\\{db_ip}\\SDPROGS$\\SDTERMINAL\\"
                
            ip_pdv = (payload.get('ip_pdv') or '').strip()
            # Se vier vazio, localhost/127.0.0.1, ou se foi solicitado alinhamento automático com o banco
            if not ip_pdv or ip_pdv.lower() in ('127.0.0.1', 'localhost', '::1', '0.0.0.0') or payload.get('auto_align_db_ip'):
                ip_pdv = db_ip
            
            cur.execute("SELECT COUNT(*) FROM FILIAIS WHERE WIDFILIAL = ?", (filial_id,))
            exists = (cur.fetchone()[0] > 0)
            
            params = (
                str(payload.get('razao', '')).strip().upper()[:60],
                str(payload.get('fantasia', '')).strip().upper()[:30],
                str(payload.get('cnpj', '')).strip().upper()[:20],
                str(payload.get('ie', '')).strip().upper()[:20],
                str(payload.get('contato', '')).strip().upper()[:50],
                str(payload.get('representante', '')).strip().upper()[:50],
                str(payload.get('email', '')).strip().upper()[:50],
                str(payload.get('telefone', '')).strip()[:30],
                str(payload.get('endereco', '')).strip().upper()[:60],
                str(payload.get('numero', '')).strip().upper()[:20],
                str(payload.get('complemento', '')).strip().upper()[:20],
                FirebirdManager.format_cep(payload.get('cep', ''))[:9],
                id_cidade,
                id_bairro,
                str(payload.get('nome_contador', '')).strip().upper()[:100],
                str(payload.get('cnpj_contador', '')).strip().upper()[:20],
                str(payload.get('cpf_contador', '')).strip()[:20],
                str(payload.get('crc_contador', '')).strip().upper()[:15],
                str(payload.get('email_contador', '')).strip().upper()[:50],
                str(payload.get('telefone_contador', '')).strip()[:30],
                str(payload.get('endereco_contador', '')).strip().upper()[:60],
                str(payload.get('numero_contador', '')).strip().upper()[:20],
                str(payload.get('complemento_contador', '')).strip().upper()[:20],
                FirebirdManager.format_cep(payload.get('cep_contador', ''))[:9],
                id_cidade_cont,
                id_bairro_cont,
                int(payload.get('filial_precos', filial_id)),
                int(payload.get('filial_estoque', filial_id)),
                int(payload.get('filial_nfe', filial_id)),
                int(payload.get('filial_saidasfiscais', filial_id)),
                int(payload.get('filial_transf', filial_id)),
                int(payload.get('filial_movimento', filial_id)),
                int(payload.get('filial_etiq', filial_id)),
                int(payload.get('filial_comanda', filial_id)),
                int(payload.get('filial_carga', filial_id)),
                str(caminho_terminal).strip().upper()[:200],
                str(ip_pdv).strip()[:20]
            )
            
            if exists:
                cur.execute("""
                    UPDATE FILIAIS SET
                        WRAZAO = ?, WFANTASIA = ?, WCNPJ = ?, WINSCRICAOESTADUAL = ?,
                        WCONTATO = ?, WNOMEREPRESENTANTE = ?, WEMAIL = ?, WTELEFONEGERAL = ?,
                        WENDERECO = ?, WNUMERO = ?, WCOMPLEMENTO = ?, WCEP = ?,
                        WIDCIDADE = ?, WIDBAIRRO = ?,
                        WNOMECONTADOR = ?, WCNPJCONTADOR = ?, WCPFCONTADOR = ?, WCRCCONTADOR = ?,
                        WEMAILCONTADOR = ?, WTELEFONECONTADOR = ?, WENDERECOCONTADOR = ?, WNUMEROCONTADOR = ?,
                        WCOMPLEMENTOCONTADOR = ?, WCEPCONTADOR = ?, WIDCIDADECONTADOR = ?, WIDBAIRROCONTADOR = ?,
                        WIDFILIALPRECOS = ?, WIDFILIALESTOQUE = ?, WIDFILIALNFE = ?, WIDFILIALSAIDASFISCAIS = ?,
                        WIDFILIALTRANSF = ?, WIDFILIALMOVIMENTO = ?, WIDFILIALETIQ = ?, WIDFILIALCOMANDA = ?,
                        WIDFILIALCARGA = ?,
                        WCAMINHOSDTERMINAL = ?, WIPPDV = ?, WUPDATETIME = CURRENT_TIMESTAMP
                    WHERE WIDFILIAL = ?
                """, params + (filial_id,))
                action_desc = f"Filial {filial_id} atualizada com sucesso no banco de dados."
            else:
                cur.execute("""
                    INSERT INTO FILIAIS (
                        WRAZAO, WFANTASIA, WCNPJ, WINSCRICAOESTADUAL,
                        WCONTATO, WNOMEREPRESENTANTE, WEMAIL, WTELEFONEGERAL,
                        WENDERECO, WNUMERO, WCOMPLEMENTO, WCEP,
                        WIDCIDADE, WIDBAIRRO,
                        WNOMECONTADOR, WCNPJCONTADOR, WCPFCONTADOR, WCRCCONTADOR,
                        WEMAILCONTADOR, WTELEFONECONTADOR, WENDERECOCONTADOR, WNUMEROCONTADOR,
                        WCOMPLEMENTOCONTADOR, WCEPCONTADOR, WIDCIDADECONTADOR, WIDBAIRROCONTADOR,
                        WIDFILIALPRECOS, WIDFILIALESTOQUE, WIDFILIALNFE, WIDFILIALSAIDASFISCAIS,
                        WIDFILIALTRANSF, WIDFILIALMOVIMENTO, WIDFILIALETIQ, WIDFILIALCOMANDA,
                        WIDFILIALCARGA,
                        WCAMINHOSDTERMINAL, WIPPDV,
                        WIDFILIAL, WIDEMPRESA, WSTATUS, WUPDATETIME
                    ) VALUES (
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?, ?, ?, ?,
                        ?,
                        ?, ?,
                        ?, 1, 'A', CURRENT_TIMESTAMP
                    )
                """, params + (filial_id,))
                action_desc = f"Nova Filial {filial_id} cadastrada com sucesso no banco de dados."

            # Sincroniza FILIAISCONTROLE
            cur.execute("UPDATE FILIAISCONTROLE SET WULTIMOACESSO = CURRENT_TIMESTAMP WHERE WIDFILIAL = ?", (filial_id,))
            if cur.rowcount == 0:
                cur.execute("SELECT COALESCE(MAX(WVERSAOBANCO), 11740) FROM FILIAISCONTROLE")
                max_v = cur.fetchone()[0]
                cur.execute("INSERT INTO FILIAISCONTROLE (WIDFILIAL, WVERSAOBANCO, WULTIMOACESSO) VALUES (?, ?, CURRENT_TIMESTAMP)", (filial_id, max_v))

            # Configura SD Sentinela automaticamente se solicitado (padrão: True)
            sentinela_msg = ""
            if payload.get('configurar_sentinela', True):
                try:
                    sent_res = FirebirdManager.save_sentinela_config(config, payload, existing_cur=cur)
                    if sent_res.get('success'):
                        sentinela_msg = " | SD Sentinela: FTP(15:00), Vendas, Transmissão NF-e e Manifesto Ativados."
                except Exception as ex_sent:
                    sentinela_msg = f" | Aviso Sentinela: {str(ex_sent)}"

            conn.commit()
            conn.close()
            return {
                "success": True,
                "message": action_desc + sentinela_msg,
                "filial_id": filial_id,
                "id_cidade": id_cidade,
                "id_bairro": id_bairro,
                "caminho_terminal": caminho_terminal,
                "ip_pdv": ip_pdv,
                "database_ip": db_ip
            }
        except Exception as e:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
            return {"success": False, "error": str(e)}

    @staticmethod
    def encode_pin(plain_pin: str) -> str:
        if not plain_pin:
            return ""
        enc_bytes = bytes([255 - ord(c) for c in str(plain_pin)])
        return enc_bytes.decode('latin1')

    @staticmethod
    def decode_pin(stored_pin: str) -> str:
        if not stored_pin:
            return ""
        try:
            raw_bytes = stored_pin.encode('latin1')
            return ''.join(chr(255 - b) for b in raw_bytes)
        except:
            return ""

    @staticmethod
    def parse_pfx_certificate(pfx_bytes: bytes, pin: str):
        if not HAS_CRYPTOGRAPHY:
            raise RuntimeError("Biblioteca cryptography não disponível no ambiente Python.")
        pin_bytes = str(pin).encode('utf-8')
        try:
            pk, cert, add_certs = pkcs12.load_key_and_certificates(pfx_bytes, pin_bytes)
        except Exception as e:
            raise ValueError(f"Senha (PIN) incorreta ou formato de certificado inválido.")
        
        if not cert:
            raise ValueError("Nenhum certificado digital principal encontrado no arquivo .pfx fornecido.")

        serial_hex = f"{cert.serial_number:X}"
        if len(serial_hex) % 2 != 0:
            serial_hex = '0' + serial_hex
        se_formatted = ' '.join(serial_hex[i:i+2] for i in range(0, len(serial_hex), 2))

        cn = ""
        ou_list = []
        o = ""
        c = ""
        s = ""
        l = ""
        e = ""
        for attr in cert.subject:
            oid_name = attr.oid._name
            val = str(attr.value or '').strip()
            if oid_name == 'commonName':
                cn = val
            elif oid_name == 'organizationalUnitName':
                ou_list.append(val)
            elif oid_name == 'organizationName':
                o = val
            elif oid_name == 'countryName':
                c = val
            elif oid_name == 'stateOrProvinceName':
                s = val
            elif oid_name == 'localityName':
                l = val
            elif oid_name == 'emailAddress':
                e = val

        ou_last = ou_list[-1] if ou_list else ""
        tecnospeed_name = f"CN={cn}, OU={ou_last}, O={o}, C={c}, S={s}, L={l}, E={e}, SE={se_formatted}"

        dt = cert.not_valid_after_utc
        dias_semana = ['Segunda-Feira', 'Terça-Feira', 'Quarta-Feira', 'Quinta-Feira', 'Sexta-Feira', 'Sábado', 'Domingo']
        dia_semana_str = dias_semana[dt.weekday()]
        vencimento_fmt = f"{dt.strftime('%d/%m/%Y')} {dia_semana_str}"
        vencimento_iso = dt.strftime('%Y-%m-%d')

        hoje = datetime.now().date()
        dias_restantes = (dt.date() - hoje).days
        if dias_restantes < 0:
            status = "Expirado"
        elif dias_restantes <= 30:
            status = f"Expira em {dias_restantes} dias"
        else:
            status = "Válido"

        cnpj_match = re.search(r'\b\d{14}\b', cn)
        cnpj = cnpj_match.group(0) if cnpj_match else ""

        return {
            "cn": cn,
            "ou": ou_last,
            "o": o,
            "c": c,
            "se": se_formatted,
            "tecnospeed_name": tecnospeed_name,
            "vencimento_formatado": vencimento_fmt,
            "vencimento_iso": vencimento_iso,
            "dias_restantes": dias_restantes,
            "status": status,
            "cnpj": cnpj
        }

    @staticmethod
    def get_nfe_config(config, filial_id=2):
        filial_id = int(filial_id)
        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        try:
            # 1. NFECONFIGURACAOFILIAIS (resiliente com SELECT *)
            cur.execute("SELECT * FROM NFECONFIGURACAOFILIAIS WHERE WIDFILIAL = ?", (filial_id,))
            row = cur.fetchone()
            row_dict = {}
            if row and cur.description:
                for idx, col_desc in enumerate(cur.description):
                    row_dict[col_desc[0].strip().upper()] = row[idx]

            # 2. Generator da NF-e
            gen_name = f"GENIDNFENUMEROF{filial_id}"
            cur.execute(f"SELECT COUNT(*) FROM RDB$GENERATORS WHERE RDB$GENERATOR_NAME = '{gen_name}'")
            gen_exists = (cur.fetchone()[0] > 0)
            gen_val = 0
            if gen_exists:
                cur.execute(f"SELECT GEN_ID({gen_name}, 0) FROM RDB$DATABASE")
                r_gen = cur.fetchone()
                gen_val = int(r_gen[0]) if r_gen else 0

            # 3. FILIAISCONTROLE
            cur.execute("SELECT WNFESERIE, WNFENUMERO FROM FILIAISCONTROLE WHERE WIDFILIAL = ?", (filial_id,))
            r_fc = cur.fetchone()
            fc_serie = (r_fc[0] or '0').strip() if r_fc else '0'
            fc_numero = int(r_fc[1]) if (r_fc and r_fc[1] is not None) else 0

            # 4. Lista de Planos de Pagamento
            planos = []
            try:
                cur.execute("SELECT WIDPLANODEPAGAMENTO, WNOMEPLANO FROM PLANOSDEPAGAMENTO ORDER BY WIDPLANODEPAGAMENTO")
                for p in cur.fetchall():
                    planos.append({"id": p[0], "nome": f"{(p[1] or '').strip()} - {p[0]}"})
            except:
                pass
            if not planos:
                planos.append({"id": 1, "nome": "À VISTA - 1"})

            conn.close()

            if row:
                pin_enc = row_dict.get('WPIN')
                pin_dec = FirebirdManager.decode_pin(pin_enc) if pin_enc else ''
                reforma_dt = row_dict.get('WDATAREFORMAPRODUCAO')
                reforma_str = reforma_dt.strftime('%d/%m/%Y') if (reforma_dt and hasattr(reforma_dt, 'strftime')) else '30/06/2026'
                has_cert = bool(row_dict.get('WARQUIVOCERTIFICADO'))

                return {
                    "success": True,
                    "exists": True,
                    "filial_id": filial_id,
                    "id_nfe_ambiente": row_dict.get('WIDNFEAMBIENTE') or 11,
                    "prazo_download": row_dict.get('WPRAZODOWNLOAD') if row_dict.get('WPRAZODOWNLOAD') is not None else 30,
                    "nomenclatura_xml": row_dict.get('WNOMENCLATURAXML') if row_dict.get('WNOMENCLATURAXML') is not None else 1,
                    "ultimo_nsu": row_dict.get('WULTIMONSU') if row_dict.get('WULTIMONSU') is not None else 0,
                    "ativar_log": (row_dict.get('WATIVARLOG') or 'N').strip().upper(),
                    "nfe_serie": row_dict.get('WNFESERIE') if row_dict.get('WNFESERIE') is not None else 0,
                    "obs_fiscal": (row_dict.get('WOBSFISCAL') or ''),
                    "email_automatico": (row_dict.get('WEMAILAUTOMATICO') == 'S'),
                    "mensagem_email": (row_dict.get('WMENSAGEMEMAIL') or ''),
                    "componente_manifesto": row_dict.get('WCOMPONENTE') if row_dict.get('WCOMPONENTE') is not None else 3,
                    "id_plano_pagto_nfce": row_dict.get('WIDPLANOPAGTONFCE') if row_dict.get('WIDPLANOPAGTONFCE') is not None else 1,
                    "exigir_contas_receber": (row_dict.get('WEXIGIRCONTASRECEBER') == 'S'),
                    "fecp": float(row_dict.get('WPFCP') if row_dict.get('WPFCP') is not None else 2.0),
                    "restricao_cst_cfop": (row_dict.get('WRESTRICAOCSTCFOP') == 'S'),
                    "nome_certificado": (row_dict.get('WNOMECERTIFICADO') or '').strip(),
                    "cnpj_software_house": (row_dict.get('WCNPJSOFTWAREHOUSE') or '04.260.756/0001-20').strip(),
                    "auditor": row_dict.get('WAUDITOR') if row_dict.get('WAUDITOR') is not None else 1,
                    "http_auditor": (row_dict.get('WHTTPAUDITOR') or 'http://validadornfe.tecnospeed.com.br:8181/validadorgui/validar').strip(),
                    "visualizar_auditor": row_dict.get('WVISUALIZARAUDITOR') if row_dict.get('WVISUALIZARAUDITOR') is not None else 2,
                    "pin_salvo": bool(pin_enc),
                    "pin_decodificado": pin_dec,
                    "componente_emissao": row_dict.get('WCOMPONENTEEMISSAO') if row_dict.get('WCOMPONENTEEMISSAO') is not None else 3,
                    "nome_arquivo_certificado": (row_dict.get('WNOMEARQUIVOCERTIFICADO') or '').strip(),
                    "limite_inutilizacao": row_dict.get('WLIMITEINUTILIZACAO') if row_dict.get('WLIMITEINUTILIZACAO') is not None else 100,
                    "mdfe_serie": row_dict.get('WMDFESERIE') if row_dict.get('WMDFESERIE') is not None else 0,
                    "ambiente": row_dict.get('WAMBIENTE') if row_dict.get('WAMBIENTE') is not None else 1,
                    "desoneracao": float(row_dict.get('WALIQUOTADESONERACAO') if row_dict.get('WALIQUOTADESONERACAO') is not None else 18.0),
                    "nfe_conjugada_cupom": (row_dict.get('WNFECONJUGADACUPOMFISCAL') == 'S'),
                    "regra_frete_di": row_dict.get('WREGRAFRETEDI') if row_dict.get('WREGRAFRETEDI') is not None else 1,
                    "novo_calculo_peso": (row_dict.get('WNOVOCALCULOPESO') == 'S'),
                    "perc_minimo_icms": float(row_dict.get('WPERCMINIMOICMS') if row_dict.get('WPERCMINIMOICMS') is not None else 0.0),
                    "tipo_nsu_especifico": (row_dict.get('WTIPONSUESPECIFICO') == 'S'),
                    "calculo_inverso_imposto": (row_dict.get('WCALCULOINVERSOIMPOSTO') == 'S'),
                    "baixar_xml_invoicy": (row_dict.get('WBAIXARXMLINVOICY') == 'S'),
                    "data_reforma_producao": reforma_str,
                    "nfe_connect": (row_dict.get('WNFECONNECT') == 'S'),
                    "emissao_sincrona": (row_dict.get('WEMISSAOSINCRONA') != 'N'),
                    "has_cert_blob": has_cert,
                    "nfe_numero_generator": gen_val,
                    "fc_nfe_serie": fc_serie,
                    "fc_nfe_numero": fc_numero,
                    "planos_pagamento": planos
                }
            else:
                return {
                    "success": True,
                    "exists": False,
                    "filial_id": filial_id,
                    "id_nfe_ambiente": 11,
                    "prazo_download": 30,
                    "nomenclatura_xml": 1,
                    "ultimo_nsu": 0,
                    "ativar_log": 'N',
                    "nfe_serie": 0,
                    "obs_fiscal": '',
                    "email_automatico": True,
                    "mensagem_email": '',
                    "componente_manifesto": 3,
                    "id_plano_pagto_nfce": 1,
                    "exigir_contas_receber": False,
                    "fecp": 2.0,
                    "restricao_cst_cfop": True,
                    "nome_certificado": '',
                    "cnpj_software_house": '04.260.756/0001-20',
                    "auditor": 1,
                    "http_auditor": 'http://validadornfe.tecnospeed.com.br:8181/validadorgui/validar',
                    "visualizar_auditor": 2,
                    "pin_salvo": False,
                    "pin_decodificado": '',
                    "componente_emissao": 3,
                    "nome_arquivo_certificado": '',
                    "limite_inutilizacao": 100,
                    "mdfe_serie": 0,
                    "ambiente": 1,
                    "desoneracao": 18.0,
                    "nfe_conjugada_cupom": False,
                    "regra_frete_di": 1,
                    "novo_calculo_peso": False,
                    "perc_minimo_icms": 0.0,
                    "tipo_nsu_especifico": False,
                    "calculo_inverso_imposto": False,
                    "baixar_xml_invoicy": False,
                    "data_reforma_producao": '30/06/2026',
                    "nfe_connect": False,
                    "emissao_sincrona": True,
                    "has_cert_blob": False,
                    "nfe_numero_generator": gen_val,
                    "fc_nfe_serie": fc_serie,
                    "fc_nfe_numero": fc_numero,
                    "planos_pagamento": planos
                }
        except Exception as e:
            try: conn.close()
            except: pass
            return {"success": False, "error": str(e)}

    @staticmethod
    def save_nfe_config(config, payload):
        filial_id = int(payload.get('filial_id', 2))
        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        try:
            limite_inutilizacao = int(payload.get('limite_inutilizacao', 100))
            prazo_download = int(payload.get('prazo_download', 30))
            nfe_serie = int(payload.get('nfe_serie', 0))
            nfe_numero = int(payload.get('nfe_numero', 0))
            fecp = float(payload.get('fecp', 2.0))
            ultimo_nsu = int(payload.get('ultimo_nsu', 0))
            desoneracao = float(payload.get('desoneracao', 18.0))
            decreto = float(payload.get('decreto', 0.0))
            nomenclatura_xml = int(payload.get('nomenclatura_xml', 1))
            ativar_log = 'S' if payload.get('ativar_log') == 'S' else 'N'
            componente_manifesto = int(payload.get('componente_manifesto', 3))
            componente_emissao = int(payload.get('componente_emissao', 3))
            id_plano_pagto = int(payload.get('id_plano_pagto_nfce', 1))
            obs_fiscal = payload.get('obs_fiscal') or None
            mensagem_email = payload.get('mensagem_email') or None

            email_aut = 'S' if payload.get('email_automatico', True) else 'N'
            validar_cst = 'S' if payload.get('validar_cst_cfop', True) else 'N'
            sincrona = 'S' if payload.get('emissao_sincrona', True) else 'N'
            exigir_cr = 'S' if payload.get('exigir_contas_receber', False) else 'N'
            calc_inv = 'S' if payload.get('calculo_inverso_imposto', False) else 'N'
            sd_conn = 'S' if payload.get('emitir_sd_connect', False) else 'N'
            nfe_conj = 'S' if payload.get('nfe_conjugada_cupom', False) else 'N'
            novo_peso = 'S' if payload.get('novo_calculo_peso', False) else 'N'
            nsu_esp = 'S' if payload.get('tipo_nsu_especifico', False) else 'N'
            invoicy = 'S' if payload.get('baixar_xml_invoicy', False) else 'N'

            reforma_raw = payload.get('data_reforma_producao', '30/06/2026')
            try:
                if '/' in reforma_raw:
                    dt_reforma = datetime.strptime(reforma_raw.strip(), '%d/%m/%Y')
                else:
                    dt_reforma = datetime.strptime(reforma_raw.strip(), '%Y-%m-%d')
            except:
                dt_reforma = datetime(2026, 6, 30)

            cnpj_sd = str(payload.get('cnpj_software_house') or '04.260.756/0001-20').strip()
            auditor = int(payload.get('auditor', 1))
            http_auditor = str(payload.get('http_auditor') or 'http://validadornfe.tecnospeed.com.br:8181/validadorgui/validar').strip()
            vis_auditor = int(payload.get('visualizar_auditor', 2))

            # 1. Tratar Certificado Digital se enviado
            cert_base64 = payload.get('cert_base64')
            cert_filename = payload.get('cert_filename', '')
            pin = payload.get('pin', '')
            
            update_cert_blob = False
            cert_blob = None
            cert_info = None

            if cert_base64:
                try:
                    cert_blob = base64.b64decode(cert_base64)
                    cert_info = FirebirdManager.parse_pfx_certificate(cert_blob, pin)
                    update_cert_blob = True
                except Exception as e:
                    conn.close()
                    return {"success": False, "error": f"Erro ao processar certificado digital: {e}"}

            # 2. Atualizar Generator do NFe
            gen_nfe = f"GENIDNFENUMEROF{filial_id}"
            cur.execute(f"SELECT COUNT(*) FROM RDB$GENERATORS WHERE RDB$GENERATOR_NAME = '{gen_nfe}'")
            if cur.fetchone()[0] == 0:
                cur.execute(f"CREATE SEQUENCE {gen_nfe}")
            cur.execute(f"SET GENERATOR {gen_nfe} TO {nfe_numero}")

            # 3. Atualizar FILIAISCONTROLE
            cur.execute(f"UPDATE FILIAISCONTROLE SET WNFESERIE = '{nfe_serie}', WNFENUMERO = {nfe_numero} WHERE WIDFILIAL = {filial_id}")

            # 4. Atualizar / Inserir NFECONFIGURACAOFILIAIS
            cur.execute("SELECT COUNT(*) FROM NFECONFIGURACAOFILIAIS WHERE WIDFILIAL = ?", (filial_id,))
            exists = (cur.fetchone()[0] > 0)

            cur.execute("SELECT FIRST 1 WIDNFEAMBIENTE FROM NFEAMBIENTE ORDER BY WIDNFEAMBIENTE")
            r_amb = cur.fetchone()
            id_amb = r_amb[0] if r_amb else 11

            nfe_cols = FirebirdManager.get_table_columns(cur, 'NFECONFIGURACAOFILIAIS')

            data_map = {
                'WPRAZODOWNLOAD': prazo_download,
                'WNOMENCLATURAXML': nomenclatura_xml,
                'WULTIMONSU': ultimo_nsu,
                'WATIVARLOG': ativar_log,
                'WNFESERIE': nfe_serie,
                'WOBSFISCAL': obs_fiscal,
                'WEMAILAUTOMATICO': email_aut,
                'WMENSAGEMEMAIL': mensagem_email,
                'WCOMPONENTE': componente_manifesto,
                'WIDPLANOPAGTONFCE': id_plano_pagto,
                'WEXIGIRCONTASRECEBER': exigir_cr,
                'WPFCP': fecp,
                'WRESTRICAOCSTCFOP': validar_cst,
                'WCNPJSOFTWAREHOUSE': cnpj_sd,
                'WAUDITOR': auditor,
                'WHTTPAUDITOR': http_auditor,
                'WVISUALIZARAUDITOR': vis_auditor,
                'WCOMPONENTEEMISSAO': componente_emissao,
                'WLIMITEINUTILIZACAO': limite_inutilizacao,
                'WALIQUOTADESONERACAO': desoneracao,
                'WNFECONJUGADACUPOMFISCAL': nfe_conj,
                'WNOVOCALCULOPESO': novo_peso,
                'WPERCMINIMOICMS': decreto,
                'WTIPONSUESPECIFICO': nsu_esp,
                'WCALCULOINVERSOIMPOSTO': calc_inv,
                'WBAIXARXMLINVOICY': invoicy,
                'WDATAREFORMAPRODUCAO': dt_reforma,
                'WNFECONNECT': sd_conn,
                'WEMISSAOSINCRONA': sincrona,
                'WCERTIFICADO': '123'
            }

            if not exists:
                insert_map = {
                    'WIDFILIAL': filial_id,
                    'WIDNFEAMBIENTE': id_amb,
                    'WMDFESERIE': 0,
                    'WAMBIENTE': 1,
                    'WREGRAFRETEDI': 1
                }
                for k, v in data_map.items():
                    insert_map[k] = v
                
                valid_insert = {k: v for k, v in insert_map.items() if k in nfe_cols}
                col_names = ", ".join(valid_insert.keys())
                placeholders = ", ".join("?" for _ in valid_insert)
                cur.execute(f"INSERT INTO NFECONFIGURACAOFILIAIS ({col_names}) VALUES ({placeholders})", tuple(valid_insert.values()))
            else:
                valid_update = {k: v for k, v in data_map.items() if k in nfe_cols}
                set_clauses = ", ".join(f"{k} = ?" for k in valid_update.keys())
                params = list(valid_update.values()) + [filial_id]
                cur.execute(f"UPDATE NFECONFIGURACAOFILIAIS SET {set_clauses} WHERE WIDFILIAL = ?", tuple(params))

            # Se enviou certificado com arquivo
            if update_cert_blob and cert_blob and cert_info:
                enc_pin = FirebirdManager.encode_pin(pin)
                cur.execute("""
                    UPDATE NFECONFIGURACAOFILIAIS SET
                        WARQUIVOCERTIFICADO = ?,
                        WNOMEARQUIVOCERTIFICADO = ?,
                        WNOMECERTIFICADO = ?,
                        WPIN = ?
                    WHERE WIDFILIAL = ?
                """, (cert_blob, cert_filename, cert_info['tecnospeed_name'], enc_pin, filial_id))

                try:
                    cert_dir = r"C:\SDSuper\Programas\Certificados"
                    if os.path.exists(cert_dir):
                        target_file_path = os.path.join(cert_dir, cert_filename)
                        with open(target_file_path, 'wb') as f_out:
                            f_out.write(cert_blob)
                except Exception:
                    pass
            elif pin and not payload.get('manter_cert_atual', False):
                enc_pin = FirebirdManager.encode_pin(pin)
                cur.execute("UPDATE NFECONFIGURACAOFILIAIS SET WPIN = ? WHERE WIDFILIAL = ?", (enc_pin, filial_id))

            conn.commit()
            conn.close()
            return {
                "success": True,
                "message": f"Configurações fiscais de NF-e e TecnoSpeed da Filial {filial_id} gravadas com sucesso!",
                "cert_info": cert_info
            }
        except Exception as e:
            try:
                conn.rollback()
                conn.close()
            except:
                pass
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_sentinela_config(config, filial_id=2):
        conn = FirebirdManager.get_connection(config)
        cur = conn.cursor()
        try:
            filial_id = int(filial_id)
            cur.execute("""
                SELECT FIRST 1 
                    WIDSENTINELA, WIDFILIAL, WNOMESENTINELA, WPERMITEFECHAR, WATIVARLOG,
                    WMOVIMENTARESTOQUE, WMONFTP, WHORAFTP, WTRANSMITIRNFE, WGERARNFE,
                    WMANIFESTOAUTOMATICO, WCONFIRMARMANIFESTO, WATIVARVENDAS, WBACKUPVENDAS
                FROM SENTINELAS
                ORDER BY WIDSENTINELA ASC
            """)
            s_row = cur.fetchone()
            sentinela_info = {}
            if s_row:
                sentinela_info = {
                    "id_sentinela": s_row[0],
                    "id_filial": s_row[1],
                    "nome": s_row[2] or "SENTINELA 1",
                    "permitir_fechar": s_row[3] or "N",
                    "ativar_log": s_row[4] or "N",
                    "movimentar_estoque": s_row[5] or "S",
                    "monitorar_ftp": int(s_row[6] or 1),
                    "hora_ftp": str(s_row[7] or "15:00").strip() or "15:00",
                    "transmitir_nfe": s_row[8] or "S",
                    "gerar_nfe": s_row[9] or "S",
                    "manifesto_auto": s_row[10] or "S",
                    "confirmar_manifesto": s_row[11] or "S",
                    "ativar_vendas": int(s_row[12] or 2),
                    "backup_vendas": s_row[13] or "S"
                }
            else:
                sentinela_info = {
                    "id_sentinela": 1,
                    "id_filial": 1,
                    "nome": "SENTINELA 1",
                    "permitir_fechar": "N",
                    "ativar_log": "N",
                    "movimentar_estoque": "S",
                    "monitorar_ftp": 1,
                    "hora_ftp": "15:00",
                    "transmitir_nfe": "S",
                    "gerar_nfe": "S",
                    "manifesto_auto": "S",
                    "confirmar_manifesto": "S",
                    "ativar_vendas": 2,
                    "backup_vendas": "S"
                }

            cur.execute("SELECT WIDFILIAL, WFANTASIA, WRAZAO FROM FILIAIS ORDER BY WIDFILIAL")
            filiais_db = cur.fetchall()

            cur.execute("SELECT WIDFILIAL, WCONTROLAR FROM SENTINELASFTPFILIAIS WHERE WIDSENTINELA = 1")
            ftp_map = {r[0]: (r[1] == 'S') for r in cur.fetchall()}

            cur.execute("SELECT WIDFILIAL, WCONTROLAR FROM SENTINELASFILIAIS WHERE WIDSENTINELA = 1")
            vendas_map = {r[0]: (r[1] == 'S') for r in cur.fetchall()}

            lista_ftp = []
            lista_vendas = []
            for f in filiais_db:
                fid = f[0]
                label = f"{fid} - {f[1] or f[2] or f'Filial {fid}'}"
                lista_ftp.append({
                    "filial_id": fid,
                    "label": label,
                    "checked": ftp_map.get(fid, (fid == filial_id or fid == 1))
                })
                lista_vendas.append({
                    "filial_id": fid,
                    "label": label,
                    "checked": vendas_map.get(fid, (fid == filial_id or fid == 1))
                })

            conn.close()
            return {
                "success": True,
                "sentinela": sentinela_info,
                "filiais_ftp": lista_ftp,
                "filiais_vendas": lista_vendas,
                "filial_id": filial_id
            }
        except Exception as e:
            try: conn.close()
            except: pass
            return {"success": False, "error": str(e)}

    @staticmethod
    def save_sentinela_config(config, payload, existing_cur=None):
        conn = None
        cur = existing_cur
        if cur is None:
            conn = FirebirdManager.get_connection(config)
            cur = conn.cursor()

        try:
            filial_id = int(payload.get('filial_id', 2))
            permitir_fechar = 'S' if payload.get('permitir_fechar') in [True, 'S', '1', 1] else 'N'
            ativar_log = 'S' if payload.get('ativar_log') in [True, 'S', '1', 1] else 'N'
            movimentar_estoque = 'N' if payload.get('movimentar_estoque') in [False, 'N', '0', 0] else 'S'
            monitorar_ftp = 1 if payload.get('monitorar_ftp', True) in [True, '1', 1, 'S'] else 0
            hora_ftp = str(payload.get('hora_ftp') or '15:00').strip()[:5] or '15:00'
            
            # WTRANSMITIRNFE: Marcado por padrão
            transmitir_nfe = 'S' if payload.get('transmitir_nfe', True) in [True, 'S', '1', 1] else 'N'
            gerar_nfe = 'S' if payload.get('gerar_nfe', True) in [True, 'S', '1', 1] else 'N'
            manifesto_auto = 'S' if payload.get('manifesto_auto', True) in [True, 'S', '1', 1] else 'N'
            confirmar_manifesto = 'S' if payload.get('confirmar_manifesto', True) in [True, 'S', '1', 1] else 'N'
            ativar_vendas = 2 if payload.get('ativar_vendas', True) in [True, '2', 2, 'S'] else 0

            cur.execute("SELECT WIDSENTINELA FROM SENTINELAS")
            sentinelas_existentes = [r[0] for r in cur.fetchall()]
            if not sentinelas_existentes:
                cur.execute("""
                    INSERT INTO SENTINELAS (
                        WIDSENTINELA, WIDFILIAL, WNOMESENTINELA, WPERMITEFECHAR, WATIVARLOG,
                        WMOVIMENTARESTOQUE, WMONFTP, WHORAFTP, WTRANSMITIRNFE, WGERARNFE,
                        WMANIFESTOAUTOMATICO, WCONFIRMARMANIFESTO, WATIVARVENDAS, WBACKUPVENDAS,
                        WATUALIZAR, WREINICIARCONECTOR, WSEMGTIN, WMANIFESTOMINUTOS, WMANIFESTOQUANTIDADE, WVERSAO
                    ) VALUES (
                        1, 1, 'SENTINELA 1', ?, ?,
                        ?, ?, ?, ?, ?,
                        ?, ?, ?, 'S',
                        'S', 'S', 'S', 60, 20, 2
                    )
                """, (
                    permitir_fechar, ativar_log, movimentar_estoque, monitorar_ftp, hora_ftp,
                    transmitir_nfe, gerar_nfe, manifesto_auto, confirmar_manifesto, ativar_vendas
                ))
                sentinelas_existentes = [1]
            else:
                for sid in sentinelas_existentes:
                    cur.execute("""
                        UPDATE SENTINELAS SET
                            WPERMITEFECHAR = ?,
                            WATIVARLOG = ?,
                            WMOVIMENTARESTOQUE = ?,
                            WMONFTP = ?,
                            WHORAFTP = ?,
                            WTRANSMITIRNFE = ?,
                            WGERARNFE = ?,
                            WMANIFESTOAUTOMATICO = ?,
                            WCONFIRMARMANIFESTO = ?,
                            WATIVARVENDAS = ?,
                            WBACKUPVENDAS = 'S',
                            WATUALIZAR = 'S',
                            WREINICIARCONECTOR = 'S',
                            WSEMGTIN = 'S'
                        WHERE WIDSENTINELA = ?
                    """, (
                        permitir_fechar, ativar_log, movimentar_estoque, monitorar_ftp, hora_ftp,
                        transmitir_nfe, gerar_nfe, manifesto_auto, confirmar_manifesto, ativar_vendas,
                        sid
                    ))

            # Atualizar ou Inserir em SENTINELASFTPFILIAIS (Ftp)
            ftp_filiais = payload.get('ftp_filiais')
            if ftp_filiais is None:
                ftp_filiais = [1, filial_id]
            else:
                ftp_filiais = [int(x) for x in ftp_filiais if str(x).isdigit()]
                if filial_id not in ftp_filiais:
                    ftp_filiais.append(filial_id)
                if 1 not in ftp_filiais:
                    ftp_filiais.append(1)

            for sid in sentinelas_existentes:
                for fid in ftp_filiais:
                    cur.execute("""
                        UPDATE OR INSERT INTO SENTINELASFTPFILIAIS (WIDSENTINELA, WIDFILIAL, WCONTROLAR)
                        VALUES (?, ?, 'S') MATCHING (WIDSENTINELA, WIDFILIAL)
                    """, (sid, int(fid)))

            # Atualizar ou Inserir em SENTINELASFILIAIS (Vendas)
            vendas_filiais = payload.get('vendas_filiais')
            if vendas_filiais is None:
                vendas_filiais = [1, filial_id]
            else:
                vendas_filiais = [int(x) for x in vendas_filiais if str(x).isdigit()]
                if filial_id not in vendas_filiais:
                    vendas_filiais.append(filial_id)
                if 1 not in vendas_filiais:
                    vendas_filiais.append(1)

            for sid in sentinelas_existentes:
                for fid in vendas_filiais:
                    cur.execute("""
                        UPDATE OR INSERT INTO SENTINELASFILIAIS (WIDSENTINELA, WIDFILIAL, WIDFILIALPDV, WCONTROLAR)
                        VALUES (?, ?, ?, 'S') MATCHING (WIDSENTINELA, WIDFILIAL)
                    """, (sid, int(fid), int(fid)))

            if conn:
                conn.commit()
                conn.close()

            return {
                "success": True,
                "message": f"SD Sentinela configurado com sucesso! Filial {filial_id} ativada no FTP, Vendas e Transmissão NF-e/Manifesto."
            }
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except:
                    pass
            return {"success": False, "error": str(e)}

def get_base_dir():
    if getattr(sys, 'frozen', False):
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass and os.path.exists(os.path.join(meipass, 'index.html')):
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_config_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

class AuthManager:
    CONFIG_FILE = os.path.join(get_config_dir(), 'auth_config.json')
    MASTER_USER = "wallacesantos"
    MASTER_PW_HASH = "8259bb1ff902cccfb670c6a2765f4e81973eaa236ea44419a1332f0beeb729ac"  # Senha: 97557090
    DEFAULT_SHEETS_URL = "https://script.google.com/macros/s/AKFYCBZQXMKCIKQO6AH8MZEKNWR65A80EFCMBLWT0OXKZERP-ALHOTXVPHK4FDZCMWBHLPWX/exec"
    active_sessions = {} # token -> {"username": username, "expires": timestamp}
    _lock = threading.Lock()

    @staticmethod
    def _hash_pw(password):
        return hashlib.sha256(str(password).strip().encode('utf-8')).hexdigest()

    @classmethod
    def load_config(cls):
        with cls._lock:
            data = None
            if os.path.exists(cls.CONFIG_FILE):
                try:
                    with open(cls.CONFIG_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                except Exception:
                    pass
            if not data or not isinstance(data, dict):
                data = {
                    "configured": True,
                    "username": cls.MASTER_USER,
                    "password_hash": cls.MASTER_PW_HASH,
                    "sheets_webhook_url": cls.DEFAULT_SHEETS_URL
                }
            # Força usuário e configuração mestre restrita
            data["configured"] = True
            data["username"] = cls.MASTER_USER
            if not data.get("password_hash"):
                data["password_hash"] = cls.MASTER_PW_HASH
            if not data.get("sheets_webhook_url"):
                data["sheets_webhook_url"] = cls.DEFAULT_SHEETS_URL
            return data

    @classmethod
    def save_config(cls, data):
        with cls._lock:
            try:
                data["configured"] = True
                data["username"] = cls.MASTER_USER
                if not data.get("password_hash"):
                    data["password_hash"] = cls.MASTER_PW_HASH
                with open(cls.CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                return True
            except Exception:
                return False

    @classmethod
    def is_configured(cls):
        return True

    @classmethod
    def setup_master(cls, username, password, sheets_url=""):
        return None

    @classmethod
    def verify_login(cls, username, password):
        cfg = cls.load_config()
        u = (username or "").strip().lower()
        pw_hash = cls._hash_pw(password)
        # Trava estrita e exclusiva para wallacesantos e senha 97557090
        if u == cls.MASTER_USER and pw_hash == cls.MASTER_PW_HASH:
            token = cls.create_session(cls.MASTER_USER)
            cls.log_to_sheets_async({
                "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                "tecnico": cls.MASTER_USER,
                "host_servidor": socket.gethostname(),
                "filial_id": "-",
                "cnpj": "-",
                "razao_social": "-",
                "tipo_evento": "Abertura do Utilitário",
                "o_que_foi_incluso": "Utilitário desbloqueado e autenticado com sucesso pelo técnico Wallace Santos.",
                "status": "Online"
            })
            return True, token
        return False, None

    @classmethod
    def change_password(cls, username, old_password, new_password):
        cfg = cls.load_config()
        if cls._hash_pw(old_password) != cfg.get("password_hash"):
            return False, "Senha atual incorreta."
        cfg["password_hash"] = cls._hash_pw(new_password)
        cls.save_config(cfg)
        return True, "Senha alterada com sucesso!"

    @classmethod
    def create_session(cls, username):
        token = secrets.token_hex(24)
        cls.active_sessions[token] = {
            "username": username,
            "expires": time.time() + 86400 # 24 horas
        }
        return token

    @classmethod
    def validate_token(cls, token):
        if not token:
            return False, None
        sess = cls.active_sessions.get(token)
        if sess and sess["expires"] > time.time():
            return True, sess["username"]
        return False, None

    @classmethod
    def logout(cls, token):
        if token in cls.active_sessions:
            del cls.active_sessions[token]

    @classmethod
    def get_sheets_url(cls):
        cfg = cls.load_config()
        return cfg.get("sheets_webhook_url", "")

    @classmethod
    def set_sheets_url(cls, url):
        cfg = cls.load_config()
        cfg["sheets_webhook_url"] = str(url or "").strip()
        cls.save_config(cfg)
        return True

    @classmethod
    def test_sheets_webhook(cls, url=None):
        target_url = url if url is not None else cls.get_sheets_url()
        target_url = str(target_url or "").strip()
        if not target_url:
            return False, "Nenhuma URL de Webhook foi informada."

        test_payload = {
            "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            "tecnico": cls.MASTER_USER,
            "host_servidor": socket.gethostname(),
            "filial_id": "Teste de Conexão",
            "cnpj": "00.000.000/0000-00",
            "razao_social": "Teste de Integração SDSuper - Wallace Santos",
            "cliente": "Teste de Integração SDSuper - Wallace Santos",
            "data_planejada_virada": datetime.now().strftime("%d/%m/%Y"),
            "tipo_evento": "Teste de Conexão",
            "o_que_foi_incluso": "Conexão de teste realizada com sucesso pelo Utilitário SDSuper.",
            "status": "Online"
        }
        try:
            headers = {"Content-Type": "application/json"}
            resp = requests.post(target_url, json=test_payload, headers=headers, timeout=15)
            
            # Se redirecionou para tela de login do Google (falta permissão pública)
            if "accounts.google.com" in getattr(resp, 'url', ''):
                return False, (
                    "Acesso Não Autorizado pelo Google: A requisição foi redirecionada para login do Google. "
                    "No Google Apps Script, clique em 'Implantar' > 'Gerenciar implantações' (ou 'Nova implantação') e certifique-se de configurar 'Quem tem acesso' = 'Qualquer pessoa' (Anyone)."
                )

            if resp.status_code in [200, 302]:
                return True, "Webhook testado com sucesso! A linha de teste foi gravada na sua planilha."
            elif resp.status_code == 404:
                m_id = re.search(r'/macros/s/([^/]+)/exec', target_url, re.IGNORECASE)
                if m_id and len(m_id.group(1)) > 20 and m_id.group(1).isupper():
                    return False, (
                        "Erro 404 (Não Encontrado): A URL informada está toda em LETRAS MAIÚSCULAS! "
                        "O Google Apps Script é estritamente sensível a maiúsculas e minúsculas no ID da implantação. "
                        "Copie a URL original exata diretamente da janela 'Implantar' da planilha com Ctrl+C sem alterar as letras."
                    )
                return False, (
                    "Erro 404 (Não Encontrado): O Google não encontrou esta implantação. "
                    "Causas comuns: 1) A URL possui letras maiúsculas/minúsculas diferentes da original; 2) A implantação foi arquivada ou o link está incompleto."
                )
            elif resp.status_code in [401, 403]:
                return False, (
                    "Erro de Permissão (401/403): Altere a permissão da implantação do Apps Script para 'Quem tem acesso: Qualquer pessoa' (Anyone)."
                )
            return False, f"Servidor retornou status HTTP {resp.status_code}."
        except Exception as e:
            return False, f"Falha ao conectar com o Google Sheets: {str(e)}"

    @classmethod
    def log_to_sheets_async(cls, payload):
        # 1. Registro permanente no histórico local (auditoria garantida mesmo sem internet)
        try:
            hist_file = os.path.join(get_config_dir(), 'historico_atendimentos.json')
            entries = []
            if os.path.exists(hist_file):
                try:
                    with open(hist_file, 'r', encoding='utf-8') as f:
                        entries = json.load(f)
                except Exception:
                    entries = []
            entries.append(payload)
            with open(hist_file, 'w', encoding='utf-8') as f:
                json.dump(entries, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

        # 2. Envio imediato para o Google Sheets caso configurado
        target_url = cls.get_sheets_url()
        if not target_url:
            return

        def _worker():
            try:
                requests.post(target_url, json=payload, timeout=15)
            except Exception:
                pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

class AppHandler(http.server.SimpleHTTPRequestHandler):
    def get_auth_token(self):
        auth = self.headers.get('Authorization', '')
        if auth.startswith('Bearer '):
            return auth.split(' ', 1)[1].strip()
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        if 'token' in params:
            return params['token'][0]
        return None

    def check_auth(self):
        token = self.get_auth_token()
        return AuthManager.validate_token(token)

    def do_GET(self):
        if self.path == '/' or self.path.startswith('/index.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            base_dir = get_base_dir()
            html_path = os.path.join(base_dir, 'index.html')
            if not os.path.exists(html_path):
                # Tenta diretório local de execução
                html_path = os.path.join(os.path.dirname(sys.executable), 'index.html')
            with open(html_path, 'rb') as f:
                self.wfile.write(f.read())
            return
        elif self.path == '/logo.png':
            base_dir = get_base_dir()
            logo_path = os.path.join(base_dir, 'logo.png')
            if not os.path.exists(logo_path):
                logo_path = os.path.join(os.path.dirname(sys.executable), 'logo.png')
            if os.path.exists(logo_path):
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.end_headers()
                with open(logo_path, 'rb') as f:
                    self.wfile.write(f.read())
                return
            self.send_error(404, "Logo Not Found")
            return
        elif self.path == '/api/auth-status':
            is_auth, user = self.check_auth()
            self.send_json({
                "is_configured": AuthManager.is_configured(),
                "is_authenticated": is_auth,
                "user": user,
                "sheets_configured": bool(AuthManager.get_sheets_url())
            })
            return
        elif self.path == '/api/sheets-config':
            is_auth, user = self.check_auth()
            if not is_auth:
                self.send_json({"success": False, "auth_error": True, "error": "Acesso não autorizado."}, 401)
                return
            self.send_json({
                "success": True, 
                "sheets_webhook_url": AuthManager.get_sheets_url(),
                "sheets_configured": bool(AuthManager.get_sheets_url())
            })
            return
        elif self.path == '/api/detect-registry':
            res = FirebirdManager.detect_registry()
            self.send_json(res)
            return
        elif self.path == '/api/local-info':
            ip = FirebirdManager.get_local_ip()
            db_ip = FirebirdManager.get_database_ip()
            self.send_json({
                "success": True,
                "local_ip": ip,
                "database_ip": db_ip,
                "suggested_terminal": f"\\\\{db_ip}\\SDPROGS$\\SDTERMINAL\\",
                "suggested_ippdv": db_ip
            })
            return
        elif self.path.startswith('/static/'):
            return super().do_GET()
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        try:
            data = json.loads(body) if body else {}
        except:
            data = {}

        # 1. Rotas de Autenticação Públicas
        if self.path == '/api/setup-master':
            self.send_json({"success": False, "error": "Acesso mestre bloqueado exclusivamente para o usuário wallacesantos."})
            return

        elif self.path == '/api/login':
            username = data.get('username', 'wallacesantos')
            password = data.get('password', '')
            ok, token = AuthManager.verify_login(username, password)
            if ok:
                self.send_json({
                    "success": True, 
                    "token": token, 
                    "username": "wallacesantos",
                    "sheets_configured": bool(AuthManager.get_sheets_url())
                })
            else:
                self.send_json({"success": False, "error": "Acesso Negado: Senha incorreta para o usuário wallacesantos. O utilitário permanece bloqueado."})
            return

        elif self.path == '/api/logout':
            token = self.get_auth_token()
            AuthManager.logout(token)
            self.send_json({"success": True})
            return

        # 2. Verificação de autenticação para todas as demais rotas
        is_auth, logged_user = self.check_auth()
        if not is_auth:
            self.send_json({"success": False, "auth_error": True, "error": "Acesso não autorizado. Por favor, realize login."}, 401)
            return

        # 3. Rotas Autenticadas de Configuração
        if self.path == '/api/change-password':
            old_pw = data.get('old_password', '')
            new_pw = data.get('new_password', '')
            if not new_pw or len(new_pw) < 4:
                self.send_json({"success": False, "error": "A nova senha deve ter no mínimo 4 caracteres."})
                return
            ok, msg = AuthManager.change_password(logged_user, old_pw, new_pw)
            self.send_json({"success": ok, "message": msg, "error": msg if not ok else None})
            return

        elif self.path == '/api/save-sheets-config':
            url = data.get('sheets_webhook_url', '')
            AuthManager.set_sheets_url(url)
            self.send_json({"success": True, "sheets_configured": bool(url)})
            return

        elif self.path == '/api/test-sheets':
            url = data.get('sheets_webhook_url')
            ok, msg = AuthManager.test_sheets_webhook(url)
            self.send_json({"success": ok, "message": msg})
            return

        elif self.path == '/api/detect-registry':
            res = FirebirdManager.detect_registry()
            self.send_json(res)
            return

        elif self.path == '/api/resolve-cidade':
            config = data.get('config', {})
            cidade_nome = data.get('cidade_nome', '')
            cidade_uf = data.get('cidade_uf', '')
            cidade_id = data.get('id_cidade')
            ibge = data.get('ibge')
            try:
                conn = FirebirdManager.get_connection(config)
                cur = conn.cursor()
                res = FirebirdManager.resolve_cidade(cur, cidade_id, cidade_nome, cidade_uf, ibge)
                conn.close()
                self.send_json({"success": True, **res})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/consult-cnpj':
            cnpj = data.get('cnpj', '')
            res = FirebirdManager.consult_cnpj_api(cnpj)
            self.send_json(res)
            return

        elif self.path == '/api/database-info':
            config = data.get('config', {})
            db_ip = FirebirdManager.get_database_ip(config)
            local_ip = FirebirdManager.get_local_ip()
            is_linux = bool(str(config.get('db_path', '')).startswith('/') or (FirebirdManager.detect_registry().get('is_linux', False)))
            self.send_json({
                "success": True,
                "database_ip": db_ip,
                "local_ip": local_ip,
                "is_linux": is_linux,
                "suggested_terminal": f"\\\\{db_ip}\\SDPROGS$\\SDTERMINAL\\",
                "suggested_ippdv": db_ip
            })
            return

        elif self.path == '/api/filial-details':
            config = data.get('config', {})
            filial_id = int(data.get('filial_id', 2))
            try:
                res = FirebirdManager.get_filial_details(config, filial_id)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/save-filial-full':
            config = data.get('config', {})
            payload = data.get('payload', {})
            try:
                res = FirebirdManager.save_filial_full(config, payload)
                if res.get('success'):
                    # Disparo automático para o Google Sheets
                    summary_desc = (
                        f"Fantasia: {payload.get('fantasia', '')} | "
                        f"Endereço: {payload.get('endereco', '')}, Nº {payload.get('numero', '')} - "
                        f"{payload.get('bairro_nome', '')}, {payload.get('cidade_nome', '')}/{payload.get('cidade_uf', '')} | "
                        f"CEP: {payload.get('cep', '')} | "
                        f"Contador: {payload.get('nome_contador', '')} (CNPJ: {payload.get('cnpj_contador', '')}) | "
                        f"Vínculos Operacionais: Preço(F{payload.get('filial_precos')}), Estoque(F{payload.get('filial_estoque')}), NFe(F{payload.get('filial_nfe')}), Saídas(F{payload.get('filial_saidasfiscais')}) | "
                        f"Terminal Rede: {payload.get('caminho_terminal', '')} | IP PDV: {payload.get('ip_pdv', '')}"
                    )
                    data_planejada = str(payload.get('data_planejada_virada', '')).strip() or "-"
                    razao_c = payload.get('razao', '') or payload.get('fantasia', '') or f"Filial {payload.get('filial_id', 2)}"
                    AuthManager.log_to_sheets_async({
                        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "tecnico": logged_user,
                        "host_servidor": config.get('host', 'localhost'),
                        "filial_id": f"Filial {payload.get('filial_id', 2)}",
                        "cnpj": payload.get('cnpj', ''),
                        "razao_social": razao_c,
                        "cliente": razao_c,
                        "data_planejada_virada": data_planejada,
                        "tipo_evento": "Inclusão / Cadastro de Filial (CNPJ)",
                        "o_que_foi_incluso": summary_desc,
                        "status": "Sucesso"
                    })
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/load':
            config = data.get('config', {})
            orig_filial = int(data.get('orig_filial', 1))
            dest_filial = int(data.get('dest_filial', 2))
            try:
                res = FirebirdManager.test_and_load(config, orig_filial, dest_filial)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        elif self.path == '/api/execute':
            config = data.get('config', {})
            payload = data.get('payload', {})
            try:
                res = FirebirdManager.execute_batch(config, payload)
                if res.get('success'):
                    # Disparo automático para o Google Sheets com dados reais do cliente e da filial
                    summary_obj = res.get('summary', {})
                    dest_f = int(payload.get('dest_filial', 2))
                    orig_f = int(payload.get('orig_filial', 1))
                    data_planejada = str(payload.get('data_planejada_virada', '')).strip() or "-"
                    
                    # Obter CNPJ e Razão Social reais do banco
                    cliente_nome = "-"
                    cliente_cnpj = "-"
                    try:
                        conn = FirebirdManager.get_connection(config)
                        cur = conn.cursor()
                        cur.execute("SELECT WIDFILIAL, WFANTASIA, WRAZAO, WCNPJ FROM FILIAIS WHERE WIDFILIAL IN (?, ?)", (dest_f, orig_f))
                        f_info = {}
                        for r in cur.fetchall():
                            f_info[r[0]] = {
                                "fantasia": (r[1] or '').strip(),
                                "razao": (r[2] or '').strip(),
                                "cnpj": (r[3] or '').strip()
                            }
                        conn.close()
                        
                        target_info = f_info.get(dest_f) or {}
                        orig_info = f_info.get(orig_f) or {}
                        cliente_nome = target_info.get('razao') or target_info.get('fantasia') or orig_info.get('razao') or orig_info.get('fantasia') or f"Filial {dest_f}"
                        cliente_cnpj = target_info.get('cnpj') or orig_info.get('cnpj') or "-"
                    except Exception:
                        pass

                    # Montar lista detalhada de o que foi feito
                    acoes_feitas = []
                    if summary_obj.get('perms_inserted', 0) > 0:
                        acoes_feitas.append(f"{summary_obj['perms_inserted']} permissões replicadas para {summary_obj.get('total_users', 0)} usuários")
                    if summary_obj.get('pdvs_updated', 0) > 0:
                        acoes_feitas.append(f"Acesso a PDVs autorizado para {summary_obj['pdvs_updated']} usuários")
                    if summary_obj.get('acesso_updated', 0) > 0:
                        acoes_feitas.append(f"Filial de login/acesso alterada para Filial {dest_f} ({summary_obj['acesso_updated']} usuários)")
                    if summary_obj.get('cadastro_updated', 0) > 0:
                        acoes_feitas.append(f"Filial de cadastro alterada para Filial {dest_f} ({summary_obj['cadastro_updated']} usuários)")
                    if summary_obj.get('promocoes_updated', 0) > 0:
                        acoes_feitas.append(f"Promoções ativas incluídas na nova Filial {dest_f} ({summary_obj['promocoes_updated']} promoções)")
                    if summary_obj.get('system_actions'):
                        acoes_feitas.extend(summary_obj['system_actions'])

                    summary_desc = " | ".join(acoes_feitas) if acoes_feitas else "Ações de filial executadas com sucesso."

                    tipo_evento = "Migração / Virada de CNPJ"
                    if payload.get('opt_filial_acesso') or payload.get('opt_gen_filial_padrao') or payload.get('opt_filial_precos_promocao'):
                        tipo_evento = "Virada Oficial do CNPJ (Momento da Virada)"
                    else:
                        tipo_evento = "Pré-Migração de CNPJ (Permissões, PDVs, Promoções)"

                    AuthManager.log_to_sheets_async({
                        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "tecnico": logged_user,
                        "host_servidor": config.get('host', 'localhost'),
                        "filial_id": f"Origem: F{orig_f} ➔ Destino: F{dest_f}",
                        "cnpj": cliente_cnpj,
                        "razao_social": cliente_nome,
                        "cliente": cliente_nome,
                        "data_planejada_virada": data_planejada,
                        "tipo_evento": tipo_evento,
                        "o_que_foi_incluso": summary_desc,
                        "status": "Sucesso"
                    })
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})

        elif self.path == '/api/nfe-config':
            config = data.get('config', {})
            filial_id = int(data.get('filial_id', 2))
            try:
                res = FirebirdManager.get_nfe_config(config, filial_id)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/read-cert-info':
            cert_base64 = data.get('cert_base64', '')
            pin = data.get('pin', '')
            if not cert_base64:
                self.send_json({"success": False, "error": "Arquivo do certificado digital não fornecido."})
                return
            try:
                cert_bytes = base64.b64decode(cert_base64)
                info = FirebirdManager.parse_pfx_certificate(cert_bytes, pin)
                self.send_json({"success": True, "cert_info": info})
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/save-nfe-config':
            config = data.get('config', {})
            payload = data.get('payload', {})
            try:
                res = FirebirdManager.save_nfe_config(config, payload)
                if res.get('success'):
                    filial_id = payload.get('filial_id', 2)
                    summary_desc = (
                        f"NF-e: Série {payload.get('nfe_serie', 0)}, Número {payload.get('nfe_numero', 0)} | "
                        f"TecnoSpeed: {payload.get('componente_emissao', 3)} | "
                        f"Certificado: {payload.get('cert_filename') or ('Certificado atualizado' if payload.get('pin') else 'Mantido')} | "
                        f"Auditor: {payload.get('auditor', 1)} | FECP: {payload.get('fecp', 2.0)}%"
                    )
                    AuthManager.log_to_sheets_async({
                        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "tecnico": logged_user,
                        "host_servidor": config.get('host', 'localhost'),
                        "filial_id": f"Filial {filial_id}",
                        "cnpj": "-",
                        "razao_social": "-",
                        "tipo_evento": "Configuração Fiscal de NF-e & Certificado Digital",
                        "o_que_foi_incluso": summary_desc,
                        "status": "Sucesso"
                    })
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/sentinela-config':
            config = data.get('config', {})
            filial_id = int(data.get('filial_id', 2))
            try:
                res = FirebirdManager.get_sentinela_config(config, filial_id)
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return

        elif self.path == '/api/save-sentinela-config':
            config = data.get('config', {})
            payload = data.get('payload', {})
            try:
                res = FirebirdManager.save_sentinela_config(config, payload)
                if res.get('success'):
                    filial_id = payload.get('filial_id', 2)
                    summary_desc = (
                        f"SD Sentinela: FTP 15:00 (Habilitado) | Vendas: Modo 2 (Habilitado) | "
                        f"Transmitir NF-e: Marcado (Sim) | Sincronizar Manifesto: Habilitado | "
                        f"Fechar: Impedir Fechamento | Log: Desativar | Filial {filial_id} vinculada"
                    )
                    AuthManager.log_to_sheets_async({
                        "data_hora": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        "tecnico": logged_user,
                        "host_servidor": config.get('host', 'localhost'),
                        "filial_id": f"Filial {filial_id}",
                        "cnpj": "-",
                        "razao_social": "-",
                        "tipo_evento": "Configuração do SD Sentinela (FTP, Vendas & Manifesto)",
                        "o_que_foi_incluso": summary_desc,
                        "status": "Sucesso"
                    })
                self.send_json(res)
            except Exception as e:
                self.send_json({"success": False, "error": str(e)})
            return
        else:
            self.send_error(404, "Endpoint not found")

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def log_message(self, format, *args):
        # Silenciar logs ruidosos de polling/request
        pass

def run():
    base_dir = get_base_dir()
    os.chdir(base_dir)
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), AppHandler) as httpd:
        url = f"http://localhost:{PORT}"
        print(f"==================================================")
        print(f"  SDSuper - Utilitário de Replicação de Filiais   ")
        print(f"  Painel ativo em: {url}")
        print(f"==================================================")
        try:
            webbrowser.open(url)
        except:
            pass
        httpd.serve_forever()

if __name__ == '__main__':
    run()
