#!/usr/bin/env python3
# こたえあわせ 単一HTMLビルド: モジュールを結合して こたえあわせ_vX.Y.html を生成
import sys
out = sys.argv[1] if len(sys.argv) > 1 else 'こたえあわせ_build.html'
html = open('ui_template.html', encoding='utf-8').read()
html = html.replace('<!-- __ENGINE__ -->', '<script>\n' + open('engine.js', encoding='utf-8').read() + '\n</script>')
html = html.replace('<!-- __NET__ -->',    '<script>\n' + open('net.js', encoding='utf-8').read() + '\n</script>')
html = html.replace('<!-- __DUMMY__ -->',  '<script>\n' + open('dummy_data.js', encoding='utf-8').read() + '\n</script>')
html = html.replace('<!-- __REAL__ -->',   '<script>\n' + open('real_decks.js', encoding='utf-8').read() + '\n</script>')
for ph in ['__ENGINE__','__NET__','__DUMMY__','__REAL__']:
    assert ph not in html, 'placeholder残存: '+ph
# newline='\n': text-mode書き込みは既定でOSのネイティブ改行に変換する。Windowsではこれが
# 毎回CRLFを混入させる原因だった（v0.8.2/v0.9で手動LF正規化が必要だった恒久対処）。
open(out, 'w', encoding='utf-8', newline='\n').write(html)
print('built', out, len(html), 'bytes')
