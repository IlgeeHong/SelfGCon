import os
import os.path as osp
import argparse
import pandas as pd
import pdb

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np

from torch_geometric.datasets import Planetoid, Coauthor, Amazon
import torch_geometric.transforms as T
from torch_geometric.utils import to_dense_adj
from torch_geometric.utils import add_self_loops

from model import *
from cluster import *

parser = argparse.ArgumentParser()
parser.add_argument('--model', type=str, default='DGI')
parser.add_argument('--dataset', type=str, default='Cora')
parser.add_argument('--split', type=str, default='PublicSplit')
parser.add_argument('--epochs', type=int, default=10000)
parser.add_argument('--n_experiments', type=int, default=1)
parser.add_argument('--n_layers', type=int, default=2) 
parser.add_argument('--channels', type=int, default=512) #512
parser.add_argument('--lr1', type=float, default=1e-3) 
parser.add_argument('--lr2', type=float, default=1e-2)
parser.add_argument('--wd2', type=float, default=0.0)
parser.add_argument('--patience', type=int, default=20)
parser.add_argument('--result_file', type=str, default="/results/DGI_node_classification_trial")
parser.add_argument('--embeddings', type=str, default="/results/DGI_node_classification_embeddings")
args = parser.parse_args()

file_path = os.getcwd() + args.result_file
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

results =[]
for exp in range(args.n_experiments): 
    if args.split == "PublicSplit":
        transform = T.Compose([T.NormalizeFeatures(),T.ToDevice(device)]) #, T.RandomNodeSplit(split="random", 
                                                                         #                   num_train_per_class = 20,
                                                                         #                   num_val = 500,
                                                                         #                   num_test = 1000)])
    if args.split == "RandomSplit":
        transform = T.Compose([T.NormalizeFeatures(),T.ToDevice(device), T.RandomNodeSplit(split="random", 
                                                                                            num_train_per_class = 20,
                                                                                            num_val = 160,
                                                                                            num_test = 1280)])

    if args.dataset in ['Cora', 'CiteSeer', 'PubMed']:
        dataset = Planetoid(root='Planetoid', name=args.dataset, transform=transform)
        data = dataset[0]
    if args.dataset in ['cs', 'physics']:
        dataset = Coauthor(args.dataset, 'public', transform=transform)
        data = dataset[0]
    if args.dataset in ['Computers', 'Photo']:
        dataset = Amazon("/Users/ilgeehong/Desktop/SemGCon/", args.dataset, transform=transform)
        data = dataset[0]

    train_idx = data.train_mask 
    val_idx = data.val_mask 
    test_idx = data.test_mask  

    in_dim = data.num_features
    hid_dim = args.channels
    out_dim = args.channels
    n_layers = args.n_layers

    dev = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    num_class = int(data.y.max().item()) + 1 
    N = data.num_nodes
    cnt_wait = 0
    best = 1e9
    best_t = 0

    ##### Train DGI model #####
    print("=== train DGI model ===")
    model = DGI(in_dim, hid_dim, out_dim, n_layers)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr1, weight_decay=0)
    loss_fn1 = nn.BCEWithLogitsLoss()
    for epoch in range(args.epochs):
        model.train()
        optimizer.zero_grad()

        idx = np.random.permutation(N)
        shuf_fts = data.x[idx,:]

        lbl_1 = torch.ones(1, N)
        lbl_2 = torch.zeros(1, N)
        lbl = torch.cat((lbl_1, lbl_2), 1)

        if torch.cuda.is_available():
            shuf_fts = shuf_fts.cuda()
            lbl = lbl.cuda()
    
        logits = model(data, shuf_fts) 
        loss = loss_fn1(logits, lbl)

        loss.backward()
        optimizer.step()

        print('Epoch={:03d}, loss={:.4f}'.format(epoch, loss.item()))
        if loss < best:
            best = loss
            best_t = epoch
            cnt_wait = 0
            torch.save(model.state_dict(), 'best_dgi.pkl')
        else:
            cnt_wait += 1

        if cnt_wait == args.patience:
            print('Early stopping!')
            break

    print('Loading {}th epoch'.format(best_t))
    model.load_state_dict(torch.load('best_dgi.pkl'))

    embeds = model.get_embedding(data)
    train_embs = embeds[train_idx]
    val_embs = embeds[val_idx]
    test_embs = embeds[test_idx]
    
    label = data.y
    feat = data.x
    
    train_labels = label[train_idx]
    val_labels = label[val_idx]
    test_labels = label[test_idx]

    train_feat = feat[train_idx]
    val_feat = feat[val_idx]
    test_feat = feat[test_idx] 

    ''' Linear Evaluation '''
    logreg = LogReg(train_embs.shape[1], num_class)
    opt = torch.optim.Adam(logreg.parameters(), lr=args.lr2, weight_decay=args.wd2)

    loss_fn2 = nn.CrossEntropyLoss()

    best_val_acc = 0
    eval_acc = 0

    for epoch in range(2000):
        logreg.train()
        opt.zero_grad()
        logits = logreg(train_embs)
        preds = torch.argmax(logits, dim=1)
        train_acc = torch.sum(preds == train_labels).float() / train_labels.shape[0]
        loss = loss_fn2(logits, train_labels)
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

        print('Epoch:{}, train_acc:{:.4f}, val_acc:{:4f}, test_acc:{:4f}'.format(epoch, train_acc, val_acc, test_acc))
        print('Linear evaluation accuracy:{:.4f}'.format(eval_acc))
    results += [['DGI', args.dataset, args.epochs, args.n_layers, args.lr1, args.lr2, args.wd2, args.channels, args.patience, eval_acc]]
    res1 = pd.DataFrame(results, columns=['model', 'dataset', 'epochs', 'layers', 'lr1', 'lr2', 'wd2', 'channels', 'patience', 'accuracy'])
    res1.to_csv(file_path + "_" + args.dataset +  ".csv", index=False)

# visualize_umap(test_embs, test_labels.numpy())    
# visualize_tsne(test_embs, test_labels.numpy())    
# visualize_pca(test_embs, test_labels.numpy())    
visualize_pca(test_embs, test_labels.numpy(), 1, 2)
visualize_pca(test_embs, test_labels.numpy(), 1, 3)
visualize_pca(test_embs, test_labels.numpy(), 2, 3)

from sklearn.metrics import silhouette_score
from sklearn.metrics import davies_bouldin_score
from sklearn.metrics import calinski_harabasz_score

results2 = []

sil = silhouette_score(test_embs,test_labels.numpy())
dav = davies_bouldin_score(test_embs,test_labels.numpy())
cal =calinski_harabasz_score(test_embs,test_labels.numpy())
print(sil, dav, cal)
# print(silhouette_score(test_logits,test_labels.numpy()))
# print(davies_bouldin_score(test_logits,test_labels.numpy()))
# print(calinski_harabasz_score(test_logits,test_labels.numpy()))
file_path2 = os.getcwd() + args.embeddings
results2 += [[args.model, args.dataset, sil, dav, cal]]
res2 = pd.DataFrame(results2, columns=['model', 'dataset', 'silhouette', 'davies', 'c-h'])
res2.to_csv(file_path2 + "_" + args.dataset +  ".csv", index=False)