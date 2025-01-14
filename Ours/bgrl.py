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

from ogb.nodeproppred import PygNodePropPredDataset
from torch_geometric.datasets import Planetoid, Coauthor, Amazon
import torch_geometric.transforms as T

from model_ogb import * 
from aug import *
from dataset import *
import pdb

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=str, default='BGRL')
parser.add_argument('--dataset', type=str, default='ogbn-arxiv')
parser.add_argument('--epochs', type=int, default=10000)
parser.add_argument('--n_experiments', type=int, default=1)
parser.add_argument('--n_layers', type=int, default=3)
parser.add_argument('--out_dim', type=int, default=256)
parser.add_argument('--hid_dim', type=int, default=256)
parser.add_argument('--pred_hid', type=int, default=256)
parser.add_argument('--lr1', type=float, default=1e-2)
parser.add_argument('--wd1', type=float, default=1e-5)
parser.add_argument('--lr2', type=float, default=1e-2)
parser.add_argument('--wd2', type=float, default=1e-4)
parser.add_argument('--fmr1', type=float, default=0.0)
parser.add_argument('--fmr2', type=float, default=0.0)
parser.add_argument('--edr1', type=float, default=0.6)
parser.add_argument('--edr2', type=float, default=0.6)
parser.add_argument('--result_file', type=str, default="/Ours/results/LAST")
args = parser.parse_args()

file_path = os.getcwd() + args.result_file
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def train(model, fmr1, edr1, fmr2, edr2, data):
    model.train()
    optimizer.zero_grad()
    new_data1 = random_aug(data, fmr1, edr1)
    new_data2 = random_aug(data, fmr2, edr2)
    new_data1 = new_data1.to(device)
    new_data2 = new_data2.to(device)
    _, _, loss = model(new_data1, new_data2)
    loss.backward()
    optimizer.step()
    scheduler.step()
    model.update_moving_average()
    return loss.item()

results =[]
for exp in range(args.n_experiments):
    data, train_idx, val_idx, test_idx = load(args.dataset, device)
    in_dim = data.num_features
    hid_dim = args.hid_dim
    out_dim = args.out_dim
    layer_config = [in_dim, hid_dim, hid_dim, out_dim]  
    n_layers = args.n_layers
    num_class = int(data.y.max().item()) + 1 
    N = data.num_nodes
    ##### Train CLGR model #####
    print("=== train CLGR model ===")
    model = BGRL(layer_config, args.pred_hid, args.epochs)
    model = model.to(device)
    optimizer = torch.optim.Adam(params=model.parameters(), lr=args.lr1, weight_decay= args.wd1)
    s = lambda epoch: epoch / 1000 if epoch < 1000 else ( 1 + np.cos((epoch-1000) * np.pi / (args.epochs - 1000))) * 0.5
    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda=s)
    for epoch in range(args.epochs):
        loss = train(model, args.fmr1, args.edr1, args.fmr2, args.edr2, data)
        print('Epoch={:03d}, loss={:.4f}'.format(epoch, loss))

    embeds = model.get_embedding(data)
    train_embs = embeds[train_idx]
    val_embs = embeds[val_idx]
    test_embs = embeds[test_idx]
    label = data.y.squeeze()
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
        # train_acc = torch.sum(preds == train_labels).float() / train_labels.shape[0]
        print(logits.shape)
        print(train_labels.shape)
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
    
    results += [['BGRL', args.dataset, args.lr1, args.hid_dim, args.epochs, args.edr1, args.fmr1, args.edr2, args.fmr2, eval_acc.item()]]
    res1 = pd.DataFrame(results, columns=['model', 'dataset', 'lr', 'hid_dim', 'epoch', 'edr1', 'fmr1', 'edr2', 'fmr2', 'accuracy'])
    res1.to_csv(file_path + "_" +  args.model + "_"  + args.dataset + ".csv", index=False)