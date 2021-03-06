import torch
from torchvision import datasets, models, transforms
import torch.optim as optim
import model
import utils
import time
import argparse
import os
import csv
# from tensorboardX import SummaryWriter
import mlflow
import mlflow.pytorch


parser = argparse.ArgumentParser()
parser.add_argument("--model", type=str, default='FashionSimpleNet', help="model")
parser.add_argument("--patience", type=int, default=3, help="early stopping patience")
parser.add_argument("--batch_size", type=int, default=256, help="batch size")
parser.add_argument("--nepochs", type=int, default=1, help="max epochs")
parser.add_argument("--lr", type=float, default=0.001, help="learning rate")
parser.add_argument("--nworkers", type=int, default=1, help="number of workers")
parser.add_argument("--seed", type=int, default=1, help="random seed")
parser.add_argument("--data", type=str, default='MNIST', help="MNIST, or FashionMNIST")
args = parser.parse_args()

#viz
# tsboard = SummaryWriter()

# Set up the device
device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print('Training on {}'.format(device))

# Set seeds. If using numpy this must be seeded too.
torch.manual_seed(args.seed)
if device== 'cuda:0':
    torch.cuda.manual_seed(args.seed)

# Setup folders for saved models and logs
if not os.path.exists('saved-models/'):
    os.mkdir('saved-models/')
if not os.path.exists('logs/'):
    os.mkdir('logs/')

# Setup folders. Each run must have it's own folder. Creates
# a logs folder for each model and each run.
out_dir = 'logs/{}'.format(args.model)
if not os.path.exists(out_dir):
    os.mkdir(out_dir)
run = 0
current_dir = '{}/run-{}'.format(out_dir, run)
while os.path.exists(current_dir):
    run += 1
    current_dir = '{}/run-{}'.format(out_dir, run)
os.mkdir(current_dir)
logfile = open('{}/log.txt'.format(current_dir), 'w')
print(args, file=logfile)

# Define transforms.
train_transforms = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))
])
val_transforms = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.1307,), (0.3081,))
])

mlflow.set_tracking_uri("http://192.168.10.25:5000")
mlflow.set_experiment(args.data)

# Create dataloaders. Use pin memory if cuda.
if args.data == 'FashionMNIST':
    trainset = datasets.FashionMNIST('./data', train=True, download=True, transform=train_transforms)
    train_loader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size,
                              shuffle=True, num_workers=args.nworkers)
    valset = datasets.FashionMNIST('./data', train=False, transform=val_transforms)
    val_loader = torch.utils.data.DataLoader(valset, batch_size=args.batch_size,
                            shuffle=True, num_workers=args.nworkers)
    print('Training on FashionMNIST')
else:
    trainset = datasets.MNIST('./data-mnist', train=True, download=True, transform=train_transforms)
    train_loader = torch.utils.data.DataLoader(trainset, batch_size=args.batch_size,
                              shuffle=True, num_workers=args.nworkers)
    valset = datasets.MNIST('./data-mnist', train=False, transform=val_transforms)
    val_loader = torch.utils.data.DataLoader(valset, batch_size=args.batch_size,
                            shuffle=True, num_workers=args.nworkers)
    print('Training on MNIST')


def run_model(net, loader, criterion, optimizer, train = True):
    running_loss = 0
    running_accuracy = 0

    # Set mode
    if train:
        net.train()
    else:
        net.eval()

    for i, (X, y) in enumerate(loader):
        # Pass to gpu or cpu
        X, y = X.to(device), y.to(device)

        # Zero the gradient
        optimizer.zero_grad()

        with torch.set_grad_enabled(train):
            output = net(X)
            _, pred = torch.max(output, 1)
            loss = criterion(output, y)

        # If on train backpropagate
        if train:
            loss.backward()
            optimizer.step()

        # Calculate stats
        running_loss += loss.item()
        running_accuracy += torch.sum(pred == y.detach())
    return running_loss / len(loader), running_accuracy.double() / len(loader.dataset)



if __name__ == '__main__':
    # Init network, criterion and early stopping
    net = model.__dict__[args.model]().to(device)
    criterion = torch.nn.CrossEntropyLoss()

    # Define optimizer
    optimizer = optim.Adam(net.parameters(), args.lr)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, 'min', patience=args.patience)

    # Train the network
    patience = args.patience
    best_train_loss = 1e4
    best_val_loss = 1e4
    best_train_acc = 0.0
    best_val_acc = 0.0
    writeFile = open('{}/stats.csv'.format(current_dir), 'a')
    writer = csv.writer(writeFile)
    writer.writerow(['Epoch', 'Train Loss', 'Train Accuracy', 'Validation Loss', 'Validation Accuracy'])
    with mlflow.start_run():
        for e in range(args.nepochs):
            start = time.time()
            train_loss, train_acc = run_model(net, train_loader,
                                          criterion, optimizer)
            val_loss, val_acc = run_model(net, val_loader,
                                          criterion, optimizer, False)
            end = time.time()

            scheduler.step(val_loss)

            # print stats
            stats = """Epoch: {}\t train loss: {:.3f}, train acc: {:.3f}\t
                    val loss: {:.3f}, val acc: {:.3f}\t
                    time: {:.1f}s""".format(e+1, train_loss, train_acc, val_loss,
                                            val_acc, end - start)
            print(stats)

            # viz
            # tsboard.add_scalar('data/train-loss',train_loss,e)
            # tsboard.add_scalar('data/val-loss',val_loss,e)
            # tsboard.add_scalar('data/val-accuracy',val_acc.item(),e)
            # tsboard.add_scalar('data/train-accuracy',train_acc.item(),e)

#             mlflow.log_metric("train_loss", train_loss)
            mlflow.log_metric(key="train_loss", value=train_loss, step=e)
            mlflow.log_metric(key="val_loss", value=val_loss, step=e)
            mlflow.log_metric(key="train_acc", value=train_acc.item(), step=e)
            mlflow.log_metric(key="val_acc", value=val_acc.item(), step=e)
            mlflow.log_param(key="lr", value=args.lr)

            # Write to csv file
            writer.writerow([e+1, train_loss, train_acc.item(), val_loss, val_acc.item()])
            # early stopping and save best model
            if val_loss < best_val_loss:
                best_train_loss = train_loss
                best_val_loss = val_loss
                best_train_acc = train_acc
                best_val_acc = val_acc
                patience = args.patience
                best_model_name = 'saved-models/{}-run-{}.pth.tar'.format(args.model, run)
                utils.save_model({
                    'arch': args.model,
                    'state_dict': net.state_dict()
                }, best_model_name)
            # else:
            #     patience -= 1
            #     if patience == 0:
            #         print('Run out of patience!')
            #         writeFile.close()
            #         # tsboard.close()
            #         break


        mlflow.log_param("model", args.model)
        mlflow.log_param("batch_size", args.batch_size)
        mlflow.log_param("epoch_number", args.nepochs)
        mlflow.log_metric("best_train_loss", best_train_loss)
        mlflow.log_metric("best_val_loss", best_val_loss)
        mlflow.log_metric("best_train_acc", best_train_acc.item())
        mlflow.log_metric("best_val_acc", best_val_acc.item())
        mlflow.pytorch.log_model(net, "models", registered_model_name=args.model + '_' + args.data)
        mlflow.log_artifact(best_model_name)


