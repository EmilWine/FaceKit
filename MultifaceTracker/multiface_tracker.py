import os
import numpy as np
import cv2
#import names
import json
import pickle
from scipy.optimize import linear_sum_assignment
from PyPCN import *
from collections import deque
from ipdb import set_trace as dbg

class names():
    ID=0
    def __init__():
        pass
    @staticmethod
    def get_full_name():
        names.ID +=1
        return names.ID


class IDMatchingManager():
    def __init__(self,classifier_path,th_similar,th_non_similar,th_symmetry,max_desc_len):
        self.prev_ids = {} 
        self.reverse_matched_id = {}
        self.th_similar = th_similar
        self.th_non_similar = th_non_similar
        self.th_symmetry = th_symmetry
        self.max_desc_len = max_desc_len

        with open(classifier_path, 'rb') as fd:
            self.classifier_MLP = pickle.load(fd)
    
    def compare_descriptors(self,desc1,desc2,th_sym):
        best_match = -1.0
        for d1 in desc1:
            for d2 in desc2:
                test_vec = np.concatenate((d1,d2))
                match_prob1 = self.classifier_MLP.predict_proba([test_vec])[:,1]
                match_prob2 = self.classifier_MLP.predict_proba([np.fft.fftshift(test_vec)])[:,1]
                if np.abs(match_prob1-match_prob2) > th_sym:
                    new_match = -1.0 ## No decision
                new_match = (match_prob1+match_prob2)*0.5
                best_match = new_match if new_match>best_match else best_match
        return best_match

    def preload_ids(self,json_file):
        with open(json_file, 'r') as fp:
            self.prev_ids = json.load(fp)
        
    def save_ids(self,json_file):
        temp_ids = {k:list(v) for k,v in self.prev_ids.items()}
        with open(json_file, 'w') as fp:
            json.dump(temp_ids,fp,indent = 4)

    def update_matches(self,new_ids):
        prev_keys = list(self.prev_ids.keys())
        prev_desc = list(self.prev_ids.values())

        new_keys = list(new_ids.keys())
        new_desc = list(new_ids.values())

        corr_mtx = np.zeros((len(prev_keys),len(new_keys)))
        for idx_prev, desc_prev in enumerate(prev_desc):
            for idx_new,desc_new in enumerate(new_desc):
                match_prob = self.compare_descriptors(desc_prev,[desc_new],self.th_symmetry)
                corr_mtx[idx_prev,idx_new] = match_prob
        row_ind, col_ind = linear_sum_assignment(-corr_mtx)
       
        # Generate new faces
        reverse_matched_id = {}
        undecided = []
        key_pairs_for_merge = []
        for r,c in zip(row_ind,col_ind):
            if corr_mtx[r,c] > 0.0: #Make sure there is a decision
                if corr_mtx[r,c] > self.th_similar: 
                    ## In case of duplication we want to merge history
                    if new_keys[c] in self.reverse_matched_id and \
                            prev_keys[r] != self.reverse_matched_id[new_keys[c]]: 
                        key_pairs_for_merge.append((prev_keys[r],self.reverse_matched_id[new_keys[c]]))
                        print ("merge",prev_keys[r],self.reverse_matched_id[new_keys[c]])
                    reverse_matched_id[new_keys[c]] = prev_keys[r]
                #elif corr_mtx[r,c] <= self.th_non_similar: ## High chances of new face or new description of same face
                #    if new_keys[c] in self.reverse_matched_id:
                #        self.prev_ids[self.reverse_matched_id[new_keys[c]]].append(new_desc[c]) #found a new desc of the face
                #        reverse_matched_id[new_keys[c]] = self.reverse_matched_id[new_keys[c]] #maintain reverse matching
                #    else: ## A totally new face
                #        assigned_key = names.get_full_name()
                #        self.prev_ids[assigned_key] = deque([new_desc[c]],self.max_desc_len)
                #        reverse_matched_id[new_keys[c]] = assigned_key

                else:
                    print("Undecided {0:.2f}".format(corr_mtx[r,c]))
                    undecided.append((r,c))
            else:
                print("Bad symmetry")
                undecided.append((r,c))
  
        ## Go through undcided and take previos match if existed
        #for (r,c) in undecided:
        #    print("Previous assign")
        #    if new_keys[c] in self.reverse_matched_id:
        #        reverse_matched_id[new_keys[c]] = self.reverse_matched_id[new_keys[c]]

        ## Assign new faces since there are mote face than db
        unassigned = np.delete(np.arange(0,len(new_keys),1),col_ind).tolist()
        undecided_c = [u[1] for u in undecided]
        for c in unassigned + undecided_c:
            if new_keys[c] in self.reverse_matched_id:
                self.prev_ids[self.reverse_matched_id[new_keys[c]]].append(new_desc[c]) #found a new desc of the face
                reverse_matched_id[new_keys[c]] = self.reverse_matched_id[new_keys[c]] #maintain reverse matching
            else: ## A totally new face
                assigned_key = names.get_full_name()
                self.prev_ids[assigned_key] = deque([new_desc[c]],self.max_desc_len)
                reverse_matched_id[new_keys[c]] = assigned_key

        self.reverse_matched_id = reverse_matched_id

    def check_match(self,id_check):
        if id_check in self.reverse_matched_id:
            return self.reverse_matched_id[id_check]


class MultifaceTracker():
    def __init__(self,classifier_path,th_similar,th_non_similar,th_symmetry,max_desc_len,*args):
        self.ids_manager = IDMatchingManager(classifier_path,th_similar,th_non_similar,th_symmetry,max_desc_len)
        self.pcn_detector = PCN(*args)


    def _normalize_desc(self,desc):
        desc = np.array(desc)
        desc /= np.linalg.norm(desc) #performane improves with normalization
        return desc.tolist() #save lists to allow json serialization

    def track_image(self,img):
        pcn_faces = self.pcn_detector.DetectAndTrack(img)

        if self.pcn_detector.CheckTrackingPeriod()==self.pcn_detector.track_period:
            new_ids = {pcn_det.id:self._normalize_desc(pcn_det.descriptor) for pcn_det in pcn_faces}
            self.ids_manager.update_matches(new_ids)

        return pcn_faces

    def detect_image(self,img):
        pcn_faces = self.pcn_detector.Detect(img)
        return pcn_faces


if __name__=="__main__":
    detection_model_path = "./model/PCN.caffemodel"
    pcn1_proto = "./model/PCN-1.prototxt"
    pcn2_proto = "./model/PCN-2.prototxt"
    pcn3_proto = "./model/PCN-3.prototxt"
    tracking_model_path = "./model/PCN-Tracking.caffemodel"
    tracking_proto = "./model/PCN-Tracking.prototxt"
    embed_model_path = "./model/resnetInception-128.caffemodel"
    embed_proto = "./model/resnetInception-128.prototxt"
    classifier_path = "./model/trained_MLPClassifier_model.clf"
    #classifier_path = "./model/trained_QuadraticDiscriminantAnalysis_model.clf"

    mface = MultifaceTracker(
            classifier_path,
            0.7,1e-6,0.02,1,
            detection_model_path,pcn1_proto,pcn2_proto,pcn3_proto,
            tracking_model_path,tracking_proto, 
            embed_model_path, embed_proto,
            40,1.45,0.5,0.5,0.98,30,0.9,1)
    frame_count = 0
    #if os.path.isfile("./tracking.json"):
    #    mface.ids_manager.preload_ids("./tracking.json")

    #cap = cv2.VideoCapture(0)
    cap = cv2.VideoCapture("steve.mp4")
    #cap = cv2.VideoCapture("office.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) # float
    writer = cv2.VideoWriter("tracked.mp4", fourcc, fps,(width,height),True)
    while cap.isOpened():
        ret, img = cap.read()
        frame_count +=1
        if img is None or img.shape[0] == 0:
            break
        for face in mface.track_image(img):
            name = mface.ids_manager.check_match(face.id)
            if name is None:
                name = "Undecided"
            PCN.DrawFace(face,img,name)

        cv2.putText(img,str(frame_count),(10,80), cv2.FONT_HERSHEY_SIMPLEX, 3,(0,255,0),3,cv2.LINE_AA)
        cv2.imshow('window', img)
        mface.pcn_detector.CheckTrackingPeriod()
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        writer.write(img)
    mface.ids_manager.save_ids("tracking.json")
    cap.release()
    writer.release()
