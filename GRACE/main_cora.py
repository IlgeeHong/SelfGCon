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

from torch_geometric.datasets import Planetoid, Coauthor, Amazon
import torch_geometric.transforms as T

from dataset import *
from model import * 
from aug import *
from cluster import *

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=str, default='CLNR')
parser.add_argument('--dataset', type=str, default='Cora')
parser.add_argument('--epochs', type=int, default=50)
parser.add_argument('--n_experiments', type=int, default=1)
parser.add_argument('--n_layers', type=int, default=2) 
parser.add_argument('--channels', type=int, default=512)
parser.add_argument('--proj_hid_dim', type=int, default=512)
parser.add_argument('--tau', type=float, default=0.5) 
parser.add_argument('--lr1', type=float, default=1e-3)
parser.add_argument('--lr2', type=float, default=5e-3)
parser.add_argument('--wd1', type=float, default=0.0)
parser.add_argument('--wd2', type=float, default=1e-4)
parser.add_argument('--edr', type=float, default=0.5)
parser.add_argument('--fmr', type=float, default=0.2)
parser.add_argument('--proj', type=str, default="standard") # dbn
parser.add_argument('--result_file', type=str, default="/GRACE/results/final")
# parser.add_argument('--result_file', type=str, default="/GRACE/results/new")
# parser.add_argument('--result_file', type=str, default="/GRACE/results/epochs_study")
parser.add_argument('--embeddings', type=str, default="/GRACE/results/embeddings")
args = parser.parse_args()

file_path = os.getcwd() + args.result_file
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

def train(model, data, fmr, edr, proj):
    model.train()
    optimizer.zero_grad()
    new_data1 = random_aug(data, fmr, edr)
    new_data2 = random_aug(data, fmr, edr)
    new_data1 = new_data1.to(device)
    new_data2 = new_data2.to(device)
    z1, z2 = model(new_data1, new_data2)   
    loss = model.loss(z1, z2, layer=proj)
    loss.backward()
    optimizer.step()
    return loss.item()

results =[]
# for epochs in [50, 100, 200, 400, 600]: #, 800, 1000, 1500, 2000
#    eval_acc_list = []
for exp in range(args.n_experiments):      
    data, train_idx, val_idx, test_idx = load(args.dataset, device)
    in_dim = data.num_features
    hid_dim = args.channels
    proj_hid_dim = args.proj_hid_dim
    n_layers = args.n_layers
    tau = args.tau
    num_class = int(data.y.max().item()) + 1 
    N = data.num_nodes
    ##### Train GRACE model #####
    print("=== train GRACE model ===")
    model = GRACE(in_dim, hid_dim, proj_hid_dim, n_layers, tau)
    model = model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr1, weight_decay=args.wd1)
    for epoch in range(args.epochs):
        loss = train(model, data, args.fmr, args.edr, args.proj)
        print('Epoch={:03d}, loss={:.4f}'.format(epoch, loss))
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
        # eval_acc_list.append(eval_acc.item())
    # eval_acc_mean = mean(eval_acc_list)
    results += [[args.model, args.dataset, args.epochs, args.lr1, args.lr2, args.wd1, args.wd2, args.channels, args.tau, args.edr, args.fmr, eval_acc.item()]]
    res1 = pd.DataFrame(results, columns=['model', 'dataset', 'epochs', 'lr1', 'lr2', 'wd1', 'wd2', 'channels', 'tau', 'edr', 'fmr', 'accuracy'])
    res1.to_csv(file_path + "_" + args.model + "_" + args.dataset + "_" + str(args.channels) + ".csv", index=False)


# visualize_umap(test_embs, test_labels.numpy())    
# visualize_tsne(test_embs, test_labels.numpy())
visualize_pca(test_embs.cpu(), test_labels.cpu().numpy(), 1, 2, path=file_path)
visualize_pca(test_embs.cpu(), test_labels.cpu().numpy(), 1, 3, path=file_path)
visualize_pca(test_embs.cpu(), test_labels.cpu().numpy(), 2, 3, path=file_path)

from sklearn.metrics import silhouette_score
from sklearn.metrics import davies_bouldin_score
from sklearn.metrics import calinski_harabasz_score

results2 = []

sil = silhouette_score(test_embs.cpu(),test_labels.cpu().numpy())
dav = davies_bouldin_score(test_embs.cpu(),test_labels.cpu().numpy())
cal =calinski_harabasz_score(test_embs.cpu(),test_labels.cpu().numpy())
print(sil, dav, cal)

file_path2 = os.getcwd() + args.embeddings
results2 += [[args.model, args.dataset, sil, dav, cal]]
res2 = pd.DataFrame(results2, columns=['model', 'dataset', 'silhouette', 'davies', 'c-h'])
res2.to_csv(file_path2 + "_" + args.dataset + "_" + args.model +  ".csv", index=False)