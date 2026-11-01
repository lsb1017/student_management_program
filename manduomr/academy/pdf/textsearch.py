"""Text positions in a PDF (pypdfium2): question numbers and the [손풀이] label.

Coordinates are PDF points with a top-left origin: (x0, top, x1, bottom), y growing downward.
"""
import re
import pypdfium2 as pdfium

QUESTION=re.compile(r'^(\d{1,2})[.)]')


def page_lines(page):
    """Characters grouped into lines → [(text, x0, top, x1, bottom)] in reading order."""
    width,height=page.get_size();tp=page.get_textpage()
    try:
        chars=[]
        for i in range(tp.count_chars()):
            ch=tp.get_text_range(i,1)
            # Whitespace boxes are degenerate; they would split lines. Words stay readable without them.
            if not ch or not ch.strip():continue
            left,bottom,right,top=tp.get_charbox(i)
            chars.append((ch,left,height-top,right,height-bottom))
    finally:tp.close()
    # Rows by baseline (glyph boxes end near it; small marks such as '.' have other centres),
    # then split a row at column gaps.
    chars.sort(key=lambda c:c[4])
    rows=[]
    for ch in chars:
        if rows and abs(ch[4]-rows[-1]['base'])<=max(3.0,(ch[4]-ch[2])*.3):rows[-1]['chars'].append(ch)
        else:rows.append({'base':ch[4],'chars':[ch]})
    lines=[]
    for row in rows:
        ordered=sorted(row['chars'],key=lambda c:c[1]);segment=[ordered[0]]
        for ch in ordered[1:]:
            if ch[1]-segment[-1][3]>40:lines.append(segment);segment=[ch]
            else:segment.append(ch)
        lines.append(segment)
    return [(''.join(c[0] for c in s),min(c[1] for c in s),min(c[2] for c in s),max(c[3] for c in s),max(c[4] for c in s)) for s in lines]


def question_starts(pdf_path,count,pattern=QUESTION):
    """Find 1..count in reading order (page, column, top). Returns {q: (page, x0, top, columns)}."""
    doc=pdfium.PdfDocument(str(pdf_path));candidates=[];sizes=[]
    try:
        for index in range(len(doc)):
            page=doc[index];width,height=page.get_size();sizes.append((width,height))
            for text,x0,top,x1,bottom in page_lines(page):
                match=pattern.match(text)
                if match:candidates.append({'q':int(match.group(1)),'page':index,'x0':x0,'top':top,'width':width})
            page.close()
    finally:doc.close()
    two_columns=any(c['x0']>c['width']*.45 for c in candidates)
    order=lambda c:(c['page'],int(two_columns and c['x0']>c['width']*.45),c['top'])
    candidates.sort(key=order)
    found={};position=(-1,-1,-1.0)
    for q in range(1,count+1):
        match=next((c for c in candidates if c['q']==q and order(c)>position),None)
        if match is None:continue
        found[q]=match;position=order(match)
    return found,sizes,two_columns


def question_regions(pdf_path,count,margin=28):
    """Each question runs from its number to the next number in the same column (or the column end)."""
    found,sizes,two_columns=question_starts(pdf_path,count)
    regions={};numbers=sorted(found)
    for i,q in enumerate(numbers):
        c=found[q];width,height=sizes[c['page']]
        column=int(two_columns and c['x0']>width*.45)
        left=margin if not two_columns else (margin if column==0 else width/2)
        right=width-margin if not two_columns else (width/2 if column==0 else width-margin)
        bottom=height-margin
        nxt=found.get(numbers[i+1]) if i+1<len(numbers) else None
        if nxt and nxt['page']==c['page'] and int(two_columns and nxt['x0']>width*.45)==column:bottom=nxt['top']-4
        regions[q]={'page':c['page'],'x0':left,'y0':max(0,c['top']-6),'x1':right,'y1':bottom}
    return regions


def find_text(pdf_path,needle):
    """All occurrences of needle → [(page, x0, top, x1, bottom)]."""
    doc=pdfium.PdfDocument(str(pdf_path));out=[]
    try:
        for index in range(len(doc)):
            page=doc[index];width,height=page.get_size();tp=page.get_textpage()
            try:
                searcher=tp.search(needle,match_case=True)
                while True:
                    hit=searcher.get_next()
                    if not hit:break
                    start,length=hit;boxes=[tp.get_charbox(i) for i in range(start,start+length)]
                    out.append((index,min(b[0] for b in boxes),height-max(b[3] for b in boxes),max(b[2] for b in boxes),height-min(b[1] for b in boxes)))
                searcher.close()
            finally:tp.close();page.close()
    finally:doc.close()
    return out


def render_region(pdf_path,page_index,box,dpi=150):
    """Crop a region (points, top-left origin) to a PIL image."""
    doc=pdfium.PdfDocument(str(pdf_path))
    try:
        page=doc[page_index];scale=dpi/72
        image=page.render(scale=scale).to_pil().convert('RGB');page.close()
    finally:doc.close()
    x0,y0,x1,y1=box
    return image.crop((int(x0*scale),int(y0*scale),int(x1*scale),int(y1*scale)))


def render_page(pdf_path,page_index,dpi=150):
    doc=pdfium.PdfDocument(str(pdf_path))
    try:
        page=doc[page_index];size=page.get_size();image=page.render(scale=dpi/72).to_pil().convert('RGB');page.close()
        return image,size
    finally:doc.close()
