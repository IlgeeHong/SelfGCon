import torch
from copy import deepcopy
import torch_geometric.transforms as T
from torch_geometric.datasets import Planetoid, Coauthor, Amazon
# from ogb.nodeproppred import PygNodePropPredDataset

def load(name, device, perturb):
    if name in ['Cora', 'CiteSeer', 'PubMed']:
        transform = T.Compose([T.NormalizeFeatures(),T.ToDevice(device)])                                                                                                          
        dataset = Planetoid(root = '/scratch/midway3/ilgee/SelfGCon/Planetoid', name=name, transform=transform)
        data = dataset[0]
        train_idx = data.train_mask 
        val_idx = data.val_mask 
        test_idx = data.test_mask  

    elif name in ['CS', 'Physics']:
        transform = T.Compose([T.ToDevice(device), T.RandomNodeSplit(split="train_rest", num_val = 0.1, num_test = 0.8)])
        dataset = Coauthor(name=name, root = '/scratch/midway3/ilgee/SelfGCon', transform=transform)
        data = dataset[0]
        train_idx = data.train_mask 
        val_idx = data.val_mask 
        test_idx = data.test_mask  

    elif name in ['Computers', 'Photo']:
        transform = T.Compose([T.ToDevice(device), T.RandomNodeSplit(split="train_rest", num_val = 0.1, num_test = 0.8)])
        dataset = Amazon(name=name, root = '/scratch/midway3/ilgee/SelfGCon', transform=transform)
        temp = dataset[0]
        noise = torch.normal(0, perturb, size=(temp.num_nodes, temp.num_features))
        noise = noise.to(device)
        data = deepcopy(temp)
        feat = temp.x + noise
        data.x = feat
        train_idx = data.train_mask 
        val_idx = data.val_mask 
        test_idx = data.test_mask  

    # elif name in ['ogbn-arxiv']:
    #     transform = T.Compose([T.ToDevice(device), T.ToUndirected()])
    #     dataset = PygNodePropPredDataset(name=name, root = '/scratch/midway3/ilgee/SelfGCon/dataset', transform=transform)
    #     data = dataset[0]
    #     split_idx = dataset.get_idx_split()
    #     train_idx = split_idx["train"]
    #     val_idx = split_idx["valid"]
    #     test_idx = split_idx["test"] 

    return data, temp, train_idx, val_idx, test_idx