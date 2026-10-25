"""Small cached line icons drawn with Qt; no icon font or new dependency."""
from functools import lru_cache
from PySide6.QtCore import Qt,QPointF,QRectF
from PySide6.QtGui import QIcon,QPixmap,QPainter,QPen,QColor,QPainterPath,QPolygonF

@lru_cache(maxsize=32)
def icon(name):
    pix=QPixmap(64,64);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.scale(2,2)
    p.setPen(QPen(QColor('#5D516E'),1.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    def line(x,y,a,b):p.drawLine(QPointF(x,y),QPointF(a,b))
    def poly(points):p.drawPolyline(QPolygonF([QPointF(*v) for v in points]))
    if name=='home':
        poly([(3,15),(16,4),(29,15)]);poly([(7,12),(7,28),(13,28),(13,20),(19,20),(19,28),(25,28),(25,12)])
    elif name=='students':
        p.drawEllipse(QRectF(9,4,10,10));p.drawRoundedRect(QRectF(5,18,20,10),4,4);p.drawArc(QRectF(17,4,10,10),-80*16,150*16);p.drawArc(QRectF(21,18,9,10),-90*16,180*16)
    elif name=='exam':
        poly([(20,3),(7,3),(7,29),(26,29),(26,9),(20,3),(20,10),(26,10)]);line(11,16,21,16);line(11,21,21,21)
    elif name=='scan':
        for points in [[(4,11),(4,5),(11,5)],[(21,5),(28,5),(28,11)],[(4,21),(4,27),(11,27)],[(21,27),(28,27),(28,21)]]:poly(points)
        line(9,16,23,16)
    elif name=='pen':poly([(5,23),(22,6),(27,11),(10,28),(4,29),(5,23),(10,28)]);line(19,9,24,14)
    elif name=='results':
        for x,y,h in [(5,18,11),(13,10,19),(21,4,25)]:p.drawRoundedRect(QRectF(x,y,5,h),1,1)
    elif name=='settings':
        p.drawEllipse(QRectF(9,9,14,14));p.drawEllipse(QRectF(13,13,6,6))
        for a,b,c,d in [(16,3,16,8),(16,24,16,29),(3,16,8,16),(24,16,29,16),(6,6,10,10),(22,22,26,26),(6,26,10,22),(22,10,26,6)]:line(a,b,c,d)
    elif name=='clock':p.drawEllipse(QRectF(4,4,24,24));poly([(16,9),(16,17),(22,17)])
    elif name=='broom':
        poly([(5,22),(14,14),(22,22),(15,29),(5,22)]);poly([(17,17),(24,4),(28,6),(21,21)]);line(10,22,15,26);line(13,19,19,24)
    elif name=='folder':poly([(3,9),(13,9),(16,12),(29,12),(26,27),(4,27),(3,9)])
    elif name=='save':
        p.drawRoundedRect(QRectF(5,4,23,25),2,2);p.drawRect(QRectF(10,4,12,9));p.drawRect(QRectF(10,20,13,9));line(19,6,19,11)
    p.end();return QIcon(pix)
