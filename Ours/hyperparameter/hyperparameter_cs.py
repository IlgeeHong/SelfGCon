import sys, os
import os.path as osp
import argparse
sys.path.append('/scratch/midway3/ilgee/SelfGCon')
import torch
import torch.nn as nn
import torch.nn.functional as F
import pandas as pd
from statistics import mean

from torch_geometric.datasets import Planetoid, Coauthor, Amazon
import torch_geometric.transforms as T
from torch_geometric.utils import to_dense_adj
from torch_geometric.utils import add_self_loops
from model_random_selection2 import * ## model
from aug import *

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=str, default='SelfGCon')
parser.add_argument('--dataset', type=str, default='CS')
parser.add_argument('--split', type=str, default='RandomSplit')
parser.add_argument('--lr1', type=float, default=1e-3) 
parser.add_argument('--wd1', type=float, default=0.0)
parser.add_argument('--result_file', type=str, default="/Ours/hyperparameter/results/Hyperparameter")
parser.add_argument('--n_experiments', type=int, default=10)
parser.add_argument('--tau', type=float, default=0.5)
args = parser.parse_args()

file_path = os.getcwd() + args.result_file
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def train(model, data, fmr, edr, k=None):
    model.train()
    optimizer.zero_grad()
    new_data1 = random_aug(data, fmr, edr)
    new_data2 = random_aug(data, fmr, edr)
    new_data1 = new_data1.to(device)
    new_data2 = new_data2.to(device)
    z1, z2 = model(new_data1, new_data2)   
    loss = model.loss(z1, z2, k)
    loss.backward()
    optimizer.step()
    return loss.item()

results =[]
for mlp_use in [True, False]:
    for channels in [256, 512]:
        for n_layers in [2]: 
            for edr in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
                for fmr in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]: 
                    for lr2 in [1e-2, 5e-3]:  
                        for wd2 in [1e-2, 1e-4]:
                            for epochs in [20, 50]:
                                best_val_acc_list = []
                                for exp in range(args.n_experiments): 
                                    if args.split == "PublicSplit":
                                        transform = T.Compose([T.NormalizeFeatures(),T.ToDevice(device)]) 
                                    if args.split == "RandomSplit":
                                        transform = T.Compose([T.ToDevice(device),T.RandomNodeSplit(split="train_rest", num_val = 0.1, num_test = 0.8)])
                                    if args.dataset in ['Cora', 'CiteSeer', 'PubMed']:
                                        dataset = Planetoid(root='Planetoid', name=args.dataset, transform=transform)
                                        data = dataset[0]
                                    if args.dataset in ['CS', 'Physics']:
                                        dataset = Coauthor("/scratch/midway3/ilgee/SelfGCon", args.dataset, transform=transform)
                                        data = dataset[0]
                                    if args.dataset in ['Computers', 'Photo']:
                                        dataset = Amazon("/scratch/midway3/ilgee/SelfGCon", args.dataset, transform=transform)
                                        data = dataset[0]

                                    train_idx = data.train_mask 
                                    val_idx = data.val_mask 
                                    test_idx = data.test_mask  
                                    in_dim = data.num_features
                                    hid_dim = channels
                                    out_dim = channels
                                    tau = args.tau
                                    num_class = int(data.y.max().item()) + 1 
                                    N = data.num_nodes

                                    ''' Model Pretraining '''
                                    model = SelfGCon(in_dim, hid_dim, out_dim, n_layers, tau, use_mlp=mlp_use)
                                    model = model.to(device)
                                    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr1, weight_decay=args.wd1)                       
                                    for epoch in range(epochs):
                                        loss = train(model, data, fmr, edr)
                                    embeds = model.get_embedding(data)
                                    train_embs = embeds[train_idx]
                                    val_embs = embeds[val_idx]
                                    test_embs = embeds[test_idx]
                                    label = data.y
                                    label = label.to(device)
                                    train_labels = label[train_idx]
                                    val_labels = label[val_idx]
                                    test_labels = label[test_idx]
                                    ''' Linear Evaluation '''
                                    logreg = LogReg(train_embs.shape[1], num_class)
                                    logreg = logreg.to(device)
                                    opt = torch.optim.Adam(logreg.parameters(), lr=lr2, weight_decay=wd2)
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
                                    # print('Linear evaluation accuracy:{:.4f}'.format(best_val_acc))                            
                                    best_val_acc_list.append(best_val_acc.item())
                                best_val_acc_mean = mean(best_val_acc_list)
                                results += [[args.model, args.dataset, epochs, n_layers, args.tau, args.lr1, args.wd1, lr2, wd2, channels, edr, fmr, mlp_use, best_val_acc_mean]]
                                res1 = pd.DataFrame(results, columns=['model', 'dataset', 'epochs', 'layers', 'tau', 'lr1', 'wd1', 'lr2', 'wd2', 'channels', 'edge_drop_rate', 'feat_mask_rate', 'mlp_use', 'val_acc'])
                                res1.to_csv(file_path + "_" + args.model + "_" + args.dataset +  ".csv", index=False)