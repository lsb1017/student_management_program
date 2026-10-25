"""Read filled bubbles relative to local paper brightness and nearby empty bubbles."""
import cv2
import numpy as np


class MarkReader:
    def __init__(self, rgb):
        self.scale=rgb.shape[1]/1682
        pixels=rgb.astype(np.float32);high=pixels.max(axis=2);low=pixels.min(axis=2)
        # A white reference around each bubble follows exposure/paper shading.
        radius=max(15,round(23*self.scale))
        paper=cv2.dilate(high,np.ones((radius*2+1,radius*2+1),np.uint8))
        contrast=paper-high
        # Green printed outlines and numbers are not neutral pen strokes.
        neutral=(high-low)<=np.maximum(12,contrast*.25)
        ink=((contrast>=42)&neutral).astype(np.float32)
        rx=max(4,round(4*self.scale));ry=max(9,round(9*self.scale))
        yy,xx=np.ogrid[-ry:ry+1,-rx:rx+1]
        kernel=((xx/rx)**2+(yy/ry)**2<=1).astype(np.float32);kernel/=kernel.sum()
        self.coverage=cv2.filter2D(ink,-1,kernel,borderType=cv2.BORDER_CONSTANT)

    def level(self,xy):
        x,y=(round(v*self.scale) for v in xy);dx=round(4*self.scale);dy=round(3*self.scale)
        # Small offsets catch off-centre strokes without entering the next bubble.
        patch=self.coverage[max(0,y-dy):y+dy+1,max(0,x-dx):x+dx+1]
        return round(float(patch.max()) if patch.size else 0,4)

    def group(self,pts,labels):
        levels=[self.level(p) for p in pts];order=np.argsort(levels)[::-1]
        top,second=levels[order[0]],levels[order[1]];background=float(np.percentile(levels,20))
        evidence=top-background;gap=top-second
        if top<.38 or evidence<.20:answer,flag=None,'blank'
        elif second>=.40 and second-background>=.22 and second>=top*.65:answer,flag=None,'multiple'
        elif top<.55 or evidence<.35 or gap<.28:answer,flag=labels[order[0]],'faint'
        else:answer,flag=labels[order[0]],'clear'
        return {'answer':answer,'flag':flag,'levels':levels,'background':round(background,4),'margin':round(gap,4)}
