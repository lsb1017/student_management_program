"""Page alignment: corner markers (generated sheets) or feature matching (external forms, scans)."""
import cv2
import numpy as np
from PIL import Image


def find_corner_squares(rgb,expected_size=None):
    """Four filled squares near the page corners → [tl,tr,br,bl] centers, or None."""
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);h,w=gray.shape
    _,mask=cv2.threshold(gray,110,255,cv2.THRESH_BINARY_INV)
    contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[]
    for contour in contours:
        x,y,cw,ch=cv2.boundingRect(contour)
        if 0.006*w<cw<0.05*w and 0.65<cw/ch<1.5 and cv2.contourArea(contour)/(cw*ch)>.72:
            candidates.append((x+cw/2,y+ch/2))
    points=[]
    for right,bottom in [(False,False),(True,False),(True,True),(False,True)]:
        near=[p for p in candidates if (p[0]>.8*w if right else p[0]<.2*w) and (p[1]>.8*h if bottom else p[1]<.2*h)]
        if not near:return None
        corner=(w if right else 0,h if bottom else 0)
        points.append(min(near,key=lambda p:(p[0]-corner[0])**2+(p[1]-corner[1])**2))
    return np.float32(points)


def warp_markers(img,targets,size,check=None):
    """Try four rotations; warp so detected corner squares land on targets. check(normalized)->bool."""
    rgb=np.array(img.convert('RGB'))
    for turns in range(4):
        arr=np.ascontiguousarray(np.rot90(rgb,turns))
        points=find_corner_squares(arr)
        if points is None:continue
        matrix=cv2.getPerspectiveTransform(points,np.float32(targets))
        normal=cv2.warpPerspective(arr,matrix,tuple(size),borderValue=(255,255,255))
        if check is None or check(normal):return Image.fromarray(normal),turns*90,matrix
    raise ValueError('양식의 네 모서리 기준점을 찾지 못했습니다. 잘림·기울기·다른 양식을 확인하세요.')


def align_features(img,reference,min_inliers=40):
    """Homography from ORB features (external forms without our markers). reference: gray ndarray."""
    gray=np.array(img.convert('L'))
    scale=min(1.0,2200/max(gray.shape))
    if scale<1:gray=cv2.resize(gray,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
    orb=cv2.ORB_create(6000)
    k1,d1=orb.detectAndCompute(reference,None);k2,d2=orb.detectAndCompute(gray,None)
    if d1 is None or d2 is None:raise ValueError('양식의 특징점을 찾지 못했습니다.')
    matches=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d2,d1,k=2)
    good=[m for m,n in (pair for pair in matches if len(pair)==2) if m.distance<.75*n.distance]
    if len(good)<min_inliers:raise ValueError('등록한 양식과 맞는 부분이 부족합니다. 다른 양식인지 확인하세요.')
    src=np.float32([k2[m.queryIdx].pt for m in good]);dst=np.float32([k1[m.trainIdx].pt for m in good])
    matrix,mask=cv2.findHomography(src,dst,cv2.RANSAC,4.0)
    if matrix is None or int(mask.sum())<min_inliers:raise ValueError('등록한 양식과 정렬하지 못했습니다.')
    if scale<1:matrix=matrix@np.diag([scale,scale,1.0])
    rgb=np.array(img.convert('RGB'))
    h,w=reference.shape
    normal=cv2.warpPerspective(rgb,matrix,(w,h),borderValue=(255,255,255))
    return Image.fromarray(normal),matrix,int(mask.sum())
