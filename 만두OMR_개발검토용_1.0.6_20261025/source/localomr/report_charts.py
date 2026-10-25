"""Vector charts with redundant grayscale/line/marker encoding for print."""
from math import cos,sin,pi
from reportlab.pdfbase import pdfmetrics


def radar(c,x,y,width,height,labels,personal,means):
    c.saveState()
    black='#203752';personal_color='#D55440';grid='#BAC1C8';fill='#F1D3C9'
    c.setStrokeColor('#8D9AA9');c.setLineWidth(.6)
    c.roundRect(x,y-12,width,height+18,6,fill=0,stroke=1)
    def text(xx,yy,value,size=8,bold=False,center=False,color=black):
        c.setFillColor(color);c.setFont('KoreanBold' if bold else 'Korean',size)
        (c.drawCentredString if center else c.drawString)(xx,yy,str(value))
    def square(xx,yy):
        c.setFillColor(personal_color);c.rect(xx-1.7,yy-1.7,3.4,3.4,fill=1,stroke=0)
    legend_y=y+height-9
    mine_width=23+pdfmetrics.stringWidth('내 점수','KoreanBold',9)
    mean_width=25+pdfmetrics.stringWidth('평균 점수','KoreanBold',9)
    legend_x=x+(width-mine_width-mean_width-20)/2
    mean_x=legend_x+mine_width+20
    c.setFillColor(fill);c.setStrokeColor(personal_color);c.setLineWidth(1.5);c.rect(legend_x,legend_y-2,17,8,fill=1,stroke=1)
    text(legend_x+23,legend_y-1,'내 점수',9,True)
    c.setStrokeColor(black);c.setDash(4,2);c.line(mean_x,legend_y+2,mean_x+19,legend_y+2);c.setDash()
    c.setFillColor('#FFFFFF');c.circle(mean_x+9.5,legend_y+2,2.2,fill=1,stroke=1)
    text(mean_x+25,legend_y-1,'평균 점수',9,True)
    if len(labels)<3:
        left=x+22;length=width-39;bottom=y+18;top=y+height-47
        for tick in range(0,101,20):
            xx=left+length*tick/100;c.setStrokeColor(grid);c.setLineWidth(.45);c.line(xx,bottom,xx,top)
            text(xx,bottom-12,tick,7,center=True)
        for i,name in enumerate(labels):
            yy=top-12-i*53;text(left,yy+10,name,8,True)
            c.setFillColor(fill);c.setStrokeColor(personal_color);c.setLineWidth(1)
            c.rect(left,yy-7,length*personal[i]/100,9,fill=1,stroke=1)
            c.setStrokeColor(black);c.setDash(4,2);c.setLineWidth(1.5);c.line(left,yy-16,left+length*means[i]/100,yy-16);c.setDash()
        c.restoreState();return
    cx=x+width/2;cy=y+(height-25)/2-1;radius=min(width*.31,(height-48)*.48)
    angles=[pi/2-2*pi*i/len(labels) for i in range(len(labels))]
    def points(values):return [(cx+radius*max(0,min(100,v))/100*cos(a),cy+radius*max(0,min(100,v))/100*sin(a)) for a,v in zip(angles,values)]
    def polygon(coords,stroke=1,do_fill=0):
        p=c.beginPath()
        for i,(xx,yy) in enumerate(coords):(p.moveTo if i==0 else p.lineTo)(xx,yy)
        p.close();c.drawPath(p,stroke=stroke,fill=do_fill)
    mine=points(personal);average=points(means)
    c.setStrokeColor(grid);c.setLineWidth(.45)
    for tick in (20,40,60,80,100):polygon(points([tick]*len(labels)))
    for a in angles:c.line(cx,cy,cx+radius*cos(a),cy+radius*sin(a))
    # Ticks belong to the background. No opaque backing boxes obscure data.
    for tick in range(0,101,20):text(cx+3,cy+radius*tick/100-2,tick,6.8,color='#87919A')
    c.saveState();c.setFillColor(personal_color);c.setFillAlpha(.24);polygon(mine,0,1);c.restoreState()
    c.setStrokeColor(personal_color);c.setLineWidth(1.6);polygon(mine)
    for xx,yy in mine:square(xx,yy)
    c.setStrokeColor(black);c.setDash(4,2);polygon(average);c.setDash()
    for xx,yy in average:
        c.setFillColor('#FFFFFF');c.circle(xx,yy,2.2,stroke=1,fill=1)
    for a,name in zip(angles,labels):
        xx=cx+(radius+17)*cos(a);yy=cy+(radius+17)*sin(a)-3
        name=str(name);lines=[name] if len(name)<=6 else [name[:6],name[6:12]+('…' if len(name)>12 else '')]
        for j,line in enumerate(lines):
            tw=pdfmetrics.stringWidth(line,'KoreanBold',7.6)
            label_x=max(x+7+tw/2,min(x+width-7-tw/2,xx))
            text(label_x,yy-j*9,line,7.6,True,True)
    c.restoreState()
