import os
import os.path as osp
import argparse
import sys
sys.path.append('/scratch/midway3/ilgee/SelfGCon')
import torch
import torch.nn as nn
import torch.nn.functional as F
import pandas as pd
from statistics import mean, stdev

from dataset import *
from model import * 
from aug import *
# from cluster import *

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=str, default='CLGR')
parser.add_argument('--dataset', type=str, default='Computers')
parser.add_argument('--n_experiments', type=int, default=20)
parser.add_argument('--n_layers', type=int, default=2)
parser.add_argument('--tau', type=float, default=0.5) 
parser.add_argument('--lr1', type=float, default=1e-3)
parser.add_argument('--wd1', type=float, default=0.0)
parser.add_argument('--lr2', type=float, default=1e-2)
parser.add_argument('--wd2', type=float, default=1e-4)
parser.add_argument('--channels', type=int, default=512) 
parser.add_argument('--fmr', type=float, default=0.0)
parser.add_argument('--edr', type=float, default=0.5)
parser.add_argument('--mlp_use', type=bool, default=False)
parser.add_argument('--result_file', type=str, default="/Ours/experiments/results/epochs_study")
args = parser.parse_args()

file_path = os.getcwd() + args.result_file
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def train(model, fmr, edr, data, k=None):
    model.train()
    optimizer.zero_grad()
    new_data1 = random_aug(data, fmr, edr)
    new_data2 = random_aug(data, fmr, edr)
    new_data1 = new_data1.to(device)
    new_data2 = new_data2.to(device)
    z1, z2 = model(new_data1, new_data2)   
    loss = model.loss(z1, z2)
    loss.backward()
    optimizer.step()
    return loss.item()

def train_semi(model, data, num_class, train_idx, k=None):
    model.train()
    optimizer.zero_grad()
    new_data1 = random_aug(data, args.fmr, args.edr)
    new_data2 = random_aug(data, args.fmr, args.edr)
    new_data1 = new_data1.to(device)
    new_data2 = new_data2.to(device)
    z1, z2 = model(new_data1, new_data2) 
    train_idx = train_idx.to(device)
    loss = model.loss(data, z1, z2, num_class, train_idx)
    loss.backward()
    optimizer.step()
    return loss.item()

results =[]
for epochs in [2500, 3000]:
    eval_acc_list = []
    for exp in range(args.n_experiments):      
        data, train_idx, val_idx, test_idx = load(args.dataset, device)
        in_dim = data.num_features
        hid_dim = args.channels
        out_dim = args.channels
        n_layers = args.n_layers
        tau = args.tau
        num_class = int(data.y.max().item()) + 1 
        N = data.num_nodes
        ##### Train CLGR model #####
        print("=== train CLGR model ===")
        model = CLGR(in_dim, hid_dim, out_dim, n_layers, tau, use_mlp = args.mlp_use) #
        model = model.to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=args.lr1, weight_decay=args.wd1)
        for epoch in range(epochs):
            loss = train(model, args.fmr, args.edr, data)
            # print('Epoch={:03d}, loss={:.4f}'.format(epoch, loss))
        embeds = model.get_embedding(data)
        train_embs = embeds[train_idx]
        val_embs = embeds[val_idx]
        test_embs = embeds[test_idx]
        label = data.y
        label = label.to(device)
        feat = data.x
        train_labels = label[train_idx]
        val_labels = label[val_idx]
        test_labels = label[test_idx]

        train_feat = feat[train_idx]
        val_feat = feat[val_idx]
        test_feat = feat[test_idx] 

        ''' Linear Evaluation '''
        logreg = LogReg(train_embs.shape[1], num_class)
        logreg = logreg.to(device)
        opt = torch.optim.Adam(logreg.parameters(), lr=args.lr2, weight_decay=args.wd2)
        loss_fn = nn.CrossEntropyLoss()

        best_val_acc = 0
        eval_acc = 0

        for epoch in range(2000):
            logreg.train()
            opt.zero_grad()
            logits = logreg(train_embs)
            preds = torch.argmax(logits, dim=1)
            train_acc = torch.sum(preds == train_labels).float() / train_labels.shape[0]
            loss = loss_fn(logits, train_labels)
            loss.backward()
            opt.step()

            logreg.eval()
            with torch.no_grad():
                val_logits = logreg(val_embs)
                test_logits = logreg(test_embs)

                val_preds = torch.argmax(val_logits, dim=1)
                test_preds = torch.argmax(test_logits, dim=1)

                val_acc = torch.sum(val_preds == val_labels).float() / val_labels.shape[0]
                test_acc = torch.sum(test_preds == test_labels).float() / test_labels.shape[0]

                if val_acc >= best_val_acc:
                    best_val_acc = val_acc
                    if test_acc > eval_acc:
                        eval_acc = test_acc
        eval_acc_list.append(eval_acc.item())
    eval_acc_mean = mean(eval_acc_list)
    results += [[args.model, args.dataset, epochs, args.lr1, args.lr2, args.wd1, args.wd2, args.channels, args.edr, args.fmr, eval_acc_mean]]
    res1 = pd.DataFrame(results, columns=['model', 'dataset', 'epochs', 'lr1', 'lr2', 'wd1', 'wd2', 'channels', 'edge_drop_rate', 'feat_mask_rate', 'accuracy'])
    res1.to_csv(file_path + "_" + args.model + "_" + args.dataset +  ".csv", index=False)
