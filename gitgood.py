from blockfrost import ApiUrls, BlockFrostApi
from pycardano import (
        PaymentSigningKey, 
        PaymentVerificationKey, 
        Address, 
        Network, 
        BlockFrostChainContext, 
        AuxiliaryData, 
        AlonzoMetadata, 
        Metadata, 
        TransactionBuilder, 
        TransactionOutput
)
from subprocess import check_output, CalledProcessError, STDOUT
import os, string, secrets, time
import click, sqlite3

__location__ = os.path.expanduser('~')
commits_db = "/commits.db"

numbers = string.digits
random = ''.join(secrets.choice(numbers) for i in range(8))

api = BlockFrostApi(project_id=os.environ['PROJECT_ID'], base_url=ApiUrls.preprod.value)
# Use testnet
network = Network.TESTNET

@click.command()
@click.option('--project-name', type=str, required=True, help="What you want your project name to be onchain.")
@click.option('--git-repo-path', type=str, required=True, help="Path to your github repository.")
@click.option('--payment-signing-key-path', type=str, required=True, help="Path to your payment signing key.")

def main(project_name, git_repo_path, payment_signing_key_path):

    payment_signing_key = PaymentSigningKey.load(payment_signing_key_path)
    payment_verification_key = PaymentVerificationKey.from_signing_key(payment_signing_key)

    from_address = str(Address(payment_verification_key.hash(), network=network))
    
    try:
        check_for_conflicts = check_output(['git', '-C', f'{git_repo_path}', 'diff', 'main...origin/main'], stderr=STDOUT, encoding='UTF-8')
        if len(check_for_conflicts) == 0:
            get_git_commit_info = check_output(['git', '-C', f'{git_repo_path}', 'log', '-1', '--date=default', '--pretty=format:%C(auto)%H,%s,%ad'], stderr=STDOUT, encoding='UTF-8')
            commit_info = get_git_commit_info.split(",")
            local_commit_hash = commit_info[0]
            commit_message = commit_info[1]
            timestamp = commit_info[2]
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='commits';")
            accounts_list = cursor.fetchall()
            if accounts_list == []:
                with open('schema.sql') as f:
                    connection.executescript(f.read())
                cursor.execute("INSERT INTO commits (onchain_id, project_name, local_commit_hash, commit_message, commit_timestamp) VALUES (?, ?, ?, ?, ?)",
                (f"{random}", f"{project_name}", f"{local_commit_hash}", f"{commit_message}", f"{timestamp}")
                )
                connection.commit()
                metadata = get_metadata(random, project_name, local_commit_hash, commit_message, timestamp)
                send_transaction(from_address, payment_signing_key, metadata, random, local_commit_hash)
            else:
                onchain_id = connection.execute(f'SELECT onchain_id FROM commits WHERE id=1').fetchone()
                duplicate = connection.execute(f'SELECT local_commit_hash FROM commits WHERE local_commit_hash="{local_commit_hash}"').fetchall()
                if not duplicate:
                    cursor.execute("INSERT INTO commits (onchain_id, project_name, local_commit_hash, commit_message, commit_timestamp) VALUES (?, ?, ?, ?, ?)",
                    (f"{onchain_id[0]}", f"{project_name}", f"{local_commit_hash}", f"{commit_message}", f"{timestamp}")
                    )
                    connection.commit()
                    metadata = get_metadata(onchain_id[0], project_name, local_commit_hash, commit_message, timestamp)
                    print("You're good, sending transaction.")
                    send_transaction(from_address, payment_signing_key, metadata, onchain_id[0], local_commit_hash)
    except CalledProcessError as e:
        print(e.output)
        connection.close()
    finally:
        connection.close()


def get_db_connection():
    connection = sqlite3.connect('commits.db')
    connection.row_factory = sqlite3.Row
    return connection


def get_metadata(onchain_id, project_name, local_commit_hash, commit_message, timestamp):
    commit_message_length = string_byte_length(commit_message)
    if commit_message_length <= 64:
        metadata = {
                    int(f"{onchain_id}"):
                            {
                            "msg":
                        [
                            f"{project_name}",
                            f"{local_commit_hash}",
                            f"{commit_message}",
                            f"{timestamp}"
                        ]
                    }
        }
    elif commit_message_length > 64:
        commit_message_part_one, commit_message_part_two = commit_message[:len(commit_message)//2], commit_message[len(commit_message)//2:]
        metadata = {
                    int(f"{onchain_id}"):
                            {
                            "msg":
                        [
                            f"{project_name}",
                            f"{local_commit_hash}",
                            f"{commit_message_part_one}",
                            f"{commit_message_part_two}",
                            f"{timestamp}"
                        ]
                    }
        }
    elif commit_message_length > 128:
        print("gitgood only supports commit strings up to 128 bytes, please amend the commit message.")
    return metadata


def send_transaction(from_address, payment_signing_key, metadata, onchain_id, local_commit_hash):
    context = BlockFrostChainContext(os.environ['PROJECT_ID'], base_url=ApiUrls.preprod.value)
    auxiliary_data = AuxiliaryData(AlonzoMetadata(metadata=Metadata(metadata)))
    utxos = context.utxos(from_address)
    builder = TransactionBuilder(context)
    builder.add_input(utxos[0])
    builder.add_input_address(from_address)
    builder.auxiliary_data = auxiliary_data
    to_address = from_address
    builder.add_output(TransactionOutput.from_primitive([to_address, 2000000]))
    signed_tx = builder.build_and_sign([payment_signing_key], change_address=from_address)
    submit = context.submit_tx(signed_tx)
    print("Transaction sent!")
    print(f"Check the transaction here: https://preprod.cardanoscan.io/transaction/{submit}.")
    print("Please note there will be a slight delay for the transaction to show up on chain.")
    time.sleep(80)
    verify_commits_onchain(onchain_id, local_commit_hash)

def verify_commits_onchain(onchain_id, local_commit_hash):
    print("Verifying that commits match.")
    onchain_commits = api.metadata_label_json(onchain_id, return_type="json")
    for commit in onchain_commits:
        onchain_commit_hash = commit['json_metadata']['msg'][1]
        if onchain_commit_hash == local_commit_hash:
            print("Latest local commit and onchain commit matches, everything is awesome.")
        else:
            print("Not the latest commit, commit is not onchain yet, or local repo is out of sync.")

def string_byte_length(s):
    return len(s.encode('utf-8'))

if __name__ == "__main__":
    main()
