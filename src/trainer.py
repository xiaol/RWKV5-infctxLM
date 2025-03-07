import os, math, time, datetime, subprocess
import torch
from torch.utils.data import DataLoader
import pytorch_lightning as pl
from pytorch_lightning.utilities import rank_zero_info, rank_zero_only

def my_save(args, trainer, dd, ff):
    if '14b-run1' in ff:
        fn = ff.split('/')[-1]
        fff = '/dev/shm/' + fn
        torch.save(dd, fff)
        subprocess.Popen(f" aws s3 mv {fff} s3://rwkv-14b-4k/{fn} --quiet", shell=True)
    elif ('world/14b' in ff) or ('world/7b' in ff):
        aa = ff.split('/')[1]
        fn = ff.split('/')[-1]
        fff = f'/dev/shm/{aa}-{fn}'
        torch.save(dd, fff)
        subprocess.Popen(f" aws s3 mv {fff} s3://rwkv-world/{aa}-{fn} --quiet", shell=True)
    else:
        if 'deepspeed_stage_3' in args.strategy:
            trainer.save_checkpoint(ff, weights_only=True)
        else:
            torch.save(dd, ff)

class train_callback(pl.Callback):
    def __init__(self, args):
        super().__init__()
        self.args = args

    def on_fit_start(self, trainer, pl_module) -> None:
        args = self.args

        # if trainer.train_dataloader:
        #     trainer.train_dataloader.dataset.datasets.global_rank = trainer.global_rank
        #     trainer.train_dataloader.dataset.datasets.world_size = trainer.world_size
        # if trainer.val_dataloaders:
        #     for dataloader in trainer.val_dataloaders:
        #         dataloader.dataset.datasets.global_rank = trainer.global_rank
        #         dataloader.dataset.datasets.world_size = trainer.world_size
        if trainer.is_global_zero:  # logging
            trainer.my_loss=0.
            trainer.my_backward_step = 0
            trainer.my_loss_sum = 0
            trainer.my_loss_count = 0
            trainer.my_token_count=0
            trainer.my_log = open(args.proj_dir + "/train_log.txt", "a")
            trainer.my_log.write(f"NEW RUN {args.my_timestamp}\n{vars(self.args)}\n")
            try:
                print(f"\n{trainer.strategy.config}\n")
                trainer.my_log.write(f"{trainer.strategy.config}\n")
            except:
                pass
            trainer.my_log.flush()
            if len(args.wandb) > 0:
                print("Login to wandb...")
                import wandb
                wandb.init(
                    project=args.wandb,
                    name=args.run_name + " " + args.my_timestamp,
                    config=args,
                    save_code=False,
                )
                trainer.my_wandb = wandb

    def on_train_batch_start(self, trainer, pl_module, batch, batch_idx):
        args = self.args
        # if args.cuda_cleanup > 0:
        #     torch.cuda.empty_cache()
        real_step = trainer.global_step + args.previous_step#args.epoch_begin * args.epoch_steps

        # LR schedule
        w_step = args.warmup_steps
        if args.lr_final == args.lr_init or args.epoch_count == 0:
            lr = args.lr_init
            if trainer.global_step < w_step:
                lr = lr * (0.2 + 0.8 * trainer.global_step / w_step)
        else:
            decay_step = real_step - args.my_pile_edecay * args.epoch_steps
            decay_total = (args.epoch_count - args.my_pile_edecay) * args.epoch_steps
            progress = (decay_step - w_step + 1) / (decay_total - w_step)
            progress = min(1, max(0, progress))

            if args.lr_final == 0 or args.lr_init == 0:  # linear decay
                lr = args.lr_init + (args.lr_final - args.lr_init) * progress
            else:  # exp decay
                lr = args.lr_init * math.exp(math.log(args.lr_final / args.lr_init) * pow(progress, 1))

            if trainer.global_step < w_step:
                lr = lr * (0.2 + 0.8 * trainer.global_step / w_step)
            # if trainer.is_global_zero:
            #     print(trainer.global_step, decay_step, decay_total, w_step, progress, lr)

        for param_group in trainer.optimizers[0].param_groups:
            if args.layerwise_lr > 0:
                param_group["lr"] = lr * param_group["my_lr_scale"]
                # print(param_group["lr"], param_group["my_lr_scale"])
            else:
                param_group["lr"] = lr

        trainer.my_lr = lr
        
        # rank_zero_info(f"{real_step} {lr}")



    def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx):
        args = self.args
        if trainer.is_global_zero:  # logging
            t_now = time.time_ns()
            token_per_step = batch[0].size(0) * batch[0].size(1) * int(args.devices)
            real_step = trainer.global_step + args.previous_step #+ args.epoch_begin * args.epoch_steps
            kt_s = 0
            try:
                t_cost = (t_now - trainer.my_time_ns) / 1e9
                kt_s = token_per_step / t_cost / 1000
                # self.log("REAL it/s", 1.0 / t_cost, prog_bar=True, on_step=True)
                # self.log("wkvf",args.forward_wkv_count,prog_bar=True, on_step=True)
                # self.log("wkvb",args.backward_wkv_count,prog_bar=True, on_step=True)
                self.log("Kt/s", kt_s, prog_bar=True, on_step=True)
            except:
                pass
            trainer.my_token_count += token_per_step
            trainer.my_time_ns = t_now
            # trainer.my_loss += trainer.my_loss_all.float().mean().item()/trainer.accumulate_grad_batches
            # self.log("back",trainer.my_backward_step, prog_bar=True, on_step=True)
            if (trainer.my_backward_step) % trainer.accumulate_grad_batches == 0:
                trainer.my_loss_sum += trainer.my_loss
                trainer.my_loss_count += 1
                trainer.my_epoch_loss = trainer.my_loss_sum / trainer.my_loss_count
                self.log("lr", trainer.my_lr, prog_bar=True, on_step=True)
                self.log("loss", trainer.my_epoch_loss, prog_bar=True, on_step=True)
                
                # self.log("s", real_step, prog_bar=True, on_step=True)

                if len(args.wandb) > 0:
                    lll = {"loss": trainer.my_loss, "lr": trainer.my_lr, "Gtokens": trainer.my_token_count / 1e9}
                    if kt_s > 0:
                        lll["kt/s"] = kt_s
                    trainer.my_wandb.log(lll, step=int(real_step+args.log_add_step)) #平移一下wandb曲线
                if args.magic_prime > 0:
                    expand_factor = 2 if args.my_qa_mask > 0 else 1
                    if int(real_step) == int(args.magic_prime * expand_factor // args.real_bsz) - 1:
                        to_save_dict = pl_module.state_dict()
                        my_save(
                            to_save_dict,
                            f"{args.proj_dir}/rwkv-final.pth",
                        )
                trainer.my_loss=0.


    def on_train_epoch_start(self, trainer, pl_module):
        args = self.args
        dataset = trainer.train_dataloader.dataset.datasets
        assert "MyDataset" in str(dataset)
        dataset.global_rank = trainer.global_rank
        dataset.real_epoch = int(args.epoch_begin + trainer.current_epoch)
        dataset.world_size = trainer.world_size
        dataset.current_warmup_step = trainer.global_step * args.micro_bsz * (args.accumulate_grad_batches or 1)
        if trainer.val_dataloaders:
            for dataloader in trainer.val_dataloaders:
                dataloader.dataset.datasets.global_rank = trainer.global_rank
                dataloader.dataset.datasets.world_size = trainer.world_size
        # print(f'########## world_size {dataset.world_size} global_rank {dataset.global_rank} real_epoch {dataset.real_epoch} ##########')

    

    # def on_train_epoch_start(self, trainer, pl_module):
    #     args = self.args
    #     if pl.__version__[0]=='2':
    #         dataset = trainer.train_dataloader.dataset
    #     else:
    #         dataset = trainer.train_dataloader.dataset.datasets
    #     assert "MyDataset" in str(dataset)
    #     dataset.global_rank = trainer.global_rank
    #     dataset.real_epoch = int(args.epoch_begin + trainer.current_epoch)
    #     dataset.world_size = trainer.world_size
    #     # print(f'########## world_size {dataset.world_size} global_rank {dataset.global_rank} real_epoch {dataset.real_epoch} ##########')

    def on_train_epoch_end(self, trainer, pl_module):
        args = self.args
        to_save_dict = {}
        if (trainer.is_global_zero) or ('deepspeed_stage_3' in args.strategy):  # save pth
            if (args.epoch_save > 0 and trainer.current_epoch % args.epoch_save == 0) or (trainer.current_epoch == args.epoch_count - 1):
                if args.data_type == 'wds_img':
                    raw_dict = pl_module.state_dict()
                    for k in raw_dict:
                        if k.startswith('encoder.') or k.startswith('decoder.'):
                            to_save_dict[k] = raw_dict[k]
                else:
                    to_save_dict = pl_module.state_dict()
                try:
                    my_save(
                        args, trainer,
                        to_save_dict,
                        f"{args.proj_dir}/rwkv-{args.epoch_begin + trainer.current_epoch}.pth",
                    )
                except Exception as e:
                    print('Error\n\n', e, '\n\n')

        if trainer.is_global_zero:  # logging
            trainer.my_log.write(f"{args.epoch_begin + trainer.current_epoch} {trainer.my_epoch_loss:.6f} {math.exp(trainer.my_epoch_loss):.4f} {trainer.my_lr:.8f} {datetime.datetime.now()} {trainer.current_epoch}\n")
            trainer.my_log.flush()

            trainer.my_loss_sum = 0
            trainer.my_loss_count = 0
            if (args.epoch_begin + trainer.current_epoch) >= args.my_exit:
                exit(0)


@rank_zero_only
def generate_init_weight(model, init_weight_name):
    mm = model.generate_init_weight()

    if model.args.my_pile_stage == 1:
        if len(model.args.load_model) > 0:
            print(f"Combine weights from {model.args.load_model}...")
            load_dict = torch.load(model.args.load_model, map_location="cpu")
            for k in load_dict:
                try:
                    assert k in mm
                except:
                    print('missing', k)
                    exit(0)
                src = load_dict[k]
                try:
                    mm[k] = src.reshape(mm[k].shape)
                except:
                    tmp = mm[k].squeeze().clone()
                    print(k, src.shape, '-->', mm[k].shape)
                    ss = src.shape[0]
                    dd = tmp.shape[0]
                    for i in range(dd):
                        pos = i / dd * ss
                        if pos >= ss - 1:
                            tmp[i] = src[ss-1]
                        else:
                            p0 = int(math.floor(pos))
                            ii = pos - p0
                            tmp[i] = src[p0] * (1-ii) + src[p0+1] * (ii)
                    mm[k] = tmp.reshape(mm[k].shape)
                    sss = src.squeeze().float().cpu().numpy()
                    print(sss[:10], '...', sss[-10:])
                    mmm = mm[k].squeeze().float().cpu().numpy()
                    print(mmm[:10], '...', mmm[-10:])

    print(f"Save to {init_weight_name}...")
    torch.save(mm, init_weight_name)

    if model.args.my_pile_stage == 1:
        print("Done. Now go for stage 2.")
        exit(0)
