#!/usr/bin/env python
# coding: utf-8

# In[ ]:

import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
import random
import pdb
from torch_geometric.nn import GCNConv

class LogReg(nn.Module):
    def __init__(self, hid_dim, out_dim):
        super(LogReg, self).__init__()
        self.fc = nn.Linear(hid_dim, out_dim)

    def forward(self, x):
        ret = self.fc(x)
        return ret


class MLP(nn.Module):
    def __init__(self, nfeat, nhid, nclass, use_bn=True):
        super(MLP, self).__init__()
        self.layer1 = nn.Linear(nfeat, nhid, bias=True)
        self.layer2 = nn.Linear(nhid, nclass, bias=True)
        self.bn = nn.BatchNorm1d(nhid)
        self.use_bn = use_bn
        self.act_fn = nn.ReLU()

    def forward(self, x, _):
        x = self.layer1(x)
        if self.use_bn:
            x = self.bn(x)
        x = self.act_fn(x)
        x = self.layer2(x)
        return x

class GCN(nn.Module):
    def __init__(self, in_dim, hid_dim, out_dim, n_layers):
        super().__init__()
        self.n_layers = n_layers
        self.convs = nn.ModuleList()
        self.convs.append(GCNConv(in_dim, hid_dim))
        if n_layers > 1:
            for i in range(n_layers - 2):
                self.convs.append(GCNConv(hid_dim, hid_dim))
            self.convs.append(GCNConv(hid_dim, out_dim))

    def forward(self, x, edge_index):
        for i in range(self.n_layers - 1):
            x = F.relu(self.convs[i](x, edge_index))
        x = self.convs[-1](x, edge_index)
        return x

class CLGR(nn.Module):
    def __init__(self, in_dim, hid_dim, out_dim, n_layers, tau, use_mlp=False):
        super().__init__()
        if not use_mlp:
            self.backbone = GCN(in_dim, hid_dim, out_dim, n_layers)
        else:
            self.backbone = MLP(in_dim, hid_dim, out_dim)
        self.tau = tau

    def get_embedding(self, data):
        out = self.backbone(data.x, data.edge_index)
        return out.detach()

    def forward(self, data1, data2):
        h1 = self.backbone(data1.x, data1.edge_index)
        h2 = self.backbone(data2.x, data2.edge_index)
        z1 = (h1 - h1.mean(0)) / h1.std(0)
        z2 = (h2 - h2.mean(0)) / h2.std(0)
        return z1, z2
    
    def sim(self, z1, z2, indices):
        z1 = F.normalize(z1)
        z2 = F.normalize(z2)
        f = lambda x: torch.exp(x / self.tau) 
        if indices is not None:
            z1_new = z1[indices,:]
            z2_new = z2[indices,:]
            sim = f(torch.mm(z1_new, z2_new.t()))
            diag = sim.diag()
        else:
            sim = f(torch.mm(z1, z2.t()))
            diag = f(torch.mm(z1, z2.t()).diag())
        return sim, diag
    
    def semi_loss(self, z1, z2, indices):
        refl_sim, refl_diag = self.sim(z1, z1, indices)
        between_sim, between_diag = self.sim(z1, z2, indices)
        semi_loss = - torch.log(between_diag / (between_sim.sum(1) + refl_sim.sum(1) - refl_diag))
        return semi_loss

    def loss(self, z1, z2, k=None, mean=True):
        if k is not None:
            N = z1.shape[0]
            indices = torch.LongTensor(random.sample(range(N), k))
        else:
            indices = None
        l1 = self.semi_loss(z1, z2, indices)
        l2 = self.semi_loss(z2, z1, indices)
        ret = (l1 + l2) * 0.5
        ret = ret.mean() if mean else ret.sum()
        return ret

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

class CCA_SSG(nn.Module):
    def __init__(self, in_dim, hid_dim, out_dim, n_layers, lambd, N, use_mlp = False):
        super().__init__()
        if not use_mlp:
            self.backbone = GCN(in_dim, hid_dim, out_dim, n_layers)
        else:
            self.backbone = MLP(in_dim, hid_dim, out_dim)
        self.lambd = lambd
        self.N = N

    def get_embedding(self, data):
        out = self.backbone(data.x, data.edge_index)
        return out.detach()

    def forward(self, data1, data2):
        h1 = self.backbone(data1.x, data1.edge_index)
        h2 = self.backbone(data2.x, data2.edge_index)
        z1 = (h1 - h1.mean(0)) / h1.std(0)
        z2 = (h2 - h2.mean(0)) / h2.std(0)
        return z1, z2
    
    def loss(self, z1, z2):
        c = torch.mm(z1.T, z2)
        c1 = torch.mm(z1.T, z1)
        c2 = torch.mm(z2.T, z2)
        c = c / self.N
        c1 = c1 / self.N
        c2 = c2 / self.N
        loss_inv = - torch.diagonal(c).sum()
        iden = torch.tensor(np.eye(c.shape[0])).to(device)
        loss_dec1 = (iden - c1).pow(2).sum()
        loss_dec2 = (iden - c2).pow(2).sum()
        lambd = self.lambd
        ret = loss_inv + lambd * (loss_dec1 + loss_dec2)
        return ret

class GRACE(nn.Module):
    def __init__(self, in_dim, hid_dim, proj_hid_dim, n_layers, tau = 0.5, use_mlp = False):
        super().__init__()
        if not use_mlp:
            self.backbone = GCN(in_dim, hid_dim, hid_dim, n_layers)
        else:
            self.backbone = MLP(in_dim, hid_dim, hid_dim)

        self.fc1 = nn.Linear(hid_dim, proj_hid_dim)
        self.fc2 = nn.Linear(proj_hid_dim, hid_dim)
        self.fc3 = nn.Linear(hid_dim, hid_dim)
        self.tau = tau
        
    def get_embedding(self, data):
        out = self.backbone(data.x, data.edge_index)
        return out.detach()

    def forward(self, data1, data2):
        z1 = self.backbone(data1.x, data1.edge_index)
        z2 = self.backbone(data2.x, data2.edge_index)
        return z1, z2
    
    def projection(self, z):
        z = F.elu(self.fc1(z))
        h = self.fc2(z)
        return h

    def sim(self, z1, z2, indices):
        z1 = F.normalize(z1)
        z2 = F.normalize(z2)
        f = lambda x: torch.exp(x / self.tau) 
        if indices is not None:
            z1_new = z1[indices,:]
            z2_new = z2[indices,:]
            sim = f(torch.mm(z1_new, z2_new.t()))
            diag = sim.diag()
        else:
            sim = f(torch.mm(z1, z2.t()))
            diag = f(torch.mm(z1, z2.t()).diag())
        return sim, diag
    
    def semi_loss(self, z1, z2, indices):
        refl_sim, refl_diag = self.sim(z1, z1, indices)
        between_sim, between_diag = self.sim(z1, z2, indices)
        semi_loss = - torch.log(between_diag / (between_sim.sum(1) + refl_sim.sum(1) - refl_diag))
        return semi_loss

    def loss(self, z1, z2, k=None, mean=True):
        if k is not None:
            N = z1.shape[0]
            indices = torch.LongTensor(random.sample(range(N), k))
        else:
            indices = None
        h1 = self.projection(z1)
        h2 = self.projection(z2)
        l1 = self.semi_loss(h1, h2, indices)
        l2 = self.semi_loss(h2, h1, indices)
        ret = (l1 + l2) * 0.5
        ret = ret.mean() if mean else ret.sum()
        return ret
